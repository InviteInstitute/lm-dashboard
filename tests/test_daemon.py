"""The daemon's tick loop. main() is an infinite loop, so each test makes
time.sleep raise a sentinel to break out after the path under test has run, and
swaps in a fake prod client."""
import pytest

from app import db
from app.pipeline import daemon, workers
from app.pipeline.client import ProdClientError


class _StopLoop(Exception):
    pass


class FakeClient:
    def __init__(self, time_pages=None, student_pages=None, raise_on_time=False):
        self.time_pages = time_pages or [[]]
        self.student_pages = student_pages or [[]]
        self.raise_on_time = raise_on_time
        self.time_calls = 0

    def page_by_time(self, date_from, limit, offset):
        self.time_calls += 1
        if self.raise_on_time:
            raise ProdClientError("simulated prod failure")
        idx = offset // limit
        return self.time_pages[idx] if idx < len(self.time_pages) else []

    def page_student(self, sid, limit, offset):
        idx = offset // limit
        return self.student_pages[idx] if idx < len(self.student_pages) else []


def _ev(eid, sid, ts="2026-06-22T10:00:00Z"):
    return {"id": eid, "studentID": sid, "classCode": "C1", "eventType": "runProject",
            "project": "{}", "raw_message": "{}", "recieved_at": ts}


@pytest.fixture
def patched_daemon(monkeypatch):
    """Patch ProdClient + time.sleep; sleep raises _StopLoop to end the loop."""
    def _setup(client, stop_after=1):
        state = {"sleeps": 0}

        def fake_sleep(_):
            state["sleeps"] += 1
            if state["sleeps"] >= stop_after:
                raise _StopLoop()

        monkeypatch.setattr(daemon, "ProdClient", lambda: client)
        monkeypatch.setattr(daemon.time, "sleep", fake_sleep)
        return state
    return _setup


def test_one_full_tick_drains_then_sleeps(patched_daemon):
    client = FakeClient(time_pages=[[]])
    patched_daemon(client, stop_after=1)
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "1"])
    assert client.time_calls >= 1          # it reached and ran a drain


def test_paused_daemon_makes_no_prod_calls(patched_daemon):
    db.set_meta("polling_enabled", "0")
    client = FakeClient()
    patched_daemon(client, stop_after=1)
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "0"])
    assert client.time_calls == 0          # paused short-circuits before drain


def test_backfills_a_new_student(patched_daemon):
    db.tracked_add("newbie")               # backfilled = 0
    client = FakeClient(time_pages=[[]], student_pages=[[_ev(1, "newbie")]])
    patched_daemon(client, stop_after=1)
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "0"])
    # backfill ran -> the roster row is now marked backfilled and state materialized
    assert db.tracked_list()[0]["backfilled"] is True
    assert db.list_student_states(["newbie"]) != []


def test_transient_prod_error_backs_off(patched_daemon):
    client = FakeClient(raise_on_time=True)
    patched_daemon(client, stop_after=1)   # the backoff sleep raises the sentinel
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "0"])
    assert client.time_calls == 1          # tried once, hit the error path


def test_drained_events_materialize_state(patched_daemon):
    db.tracked_add("s1")
    db.mark_backfilled("s1")               # skip backfill; exercise the drain path
    client = FakeClient(time_pages=[[_ev(1, "s1")]])
    patched_daemon(client, stop_after=1)
    workers.reset()
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "0"])
    assert db._query("SELECT 1 FROM vex_log WHERE studentID='s1'") != []


def _raise(*_a, **_k):
    raise RuntimeError("simulated failure")


def test_backfill_error_is_logged_not_fatal(patched_daemon, monkeypatch):
    db.tracked_add("s1")                    # unbackfilled -> backfill attempted
    monkeypatch.setattr(daemon.poller, "backfill_student", _raise)
    patched_daemon(FakeClient(), stop_after=1)
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "0"])
    assert db.tracked_list()[0]["backfilled"] is False   # failed backfill not marked done


def test_inference_error_is_logged_not_fatal(patched_daemon, monkeypatch):
    class BadWorker:
        student_id = "s1"
        def recompute_and_write(self, disabled=None):
            raise RuntimeError("inference blew up")
    monkeypatch.setattr(daemon.workers, "dirty_workers", lambda: [BadWorker()])
    patched_daemon(FakeClient(), stop_after=1)
    with pytest.raises(_StopLoop):         # the loop survives the inference error
        daemon.main(["--backfill-hours", "0"])


def test_trigger_eval_error_is_logged_not_fatal(patched_daemon, monkeypatch):
    monkeypatch.setattr(daemon.triggers, "evaluate", _raise)
    patched_daemon(FakeClient(), stop_after=1)
    with pytest.raises(_StopLoop):
        daemon.main(["--backfill-hours", "0"])
