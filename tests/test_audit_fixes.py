"""Regression tests for the 2026-09-25 bug audit."""

import io
import zipfile
from datetime import timedelta

from app import db
from app.pipeline import poller, workers


class _TimeClient:
    """Serves page_by_time pages the way prod does: newest-first."""

    def __init__(self, pages):
        self.pages = pages

    def page_by_time(self, date_from, limit, offset):
        idx = offset // limit
        return self.pages[idx] if idx < len(self.pages) else []


def _ev(eid, sid, ts):
    return {
        "id": eid,
        "studentID": sid,
        "classCode": "C1",
        "eventType": "runProject",
        "project": "{}",
        "raw_message": "{}",
        "recieved_at": ts,
    }


def test_drain_feeds_a_newest_first_page_oldest_first():
    """Prod pages newest-first. Routing in page order fed the worker backwards,
    so runs in one tick were numbered newest-first and an outcome could land on
    the wrong run."""
    db.tracked_add("d1")
    db.mark_backfilled("d1")
    stamps = ["2026-09-25T10:00:00Z", "2026-09-25T10:00:05Z", "2026-09-25T10:00:10Z"]
    page = [_ev(i + 1, "d1", t) for i, t in enumerate(stamps)][::-1]  # newest-first
    cursor = poller.get_cursor()
    poller.drain(_TimeClient([page]), cursor, limit=500, tracked={"d1"})
    w = workers.get_worker("d1")
    w.recompute_and_write()
    ts = [r["ts"] for r in db.list_student_states(["d1"])[0]["runs"]["runs"]]
    assert len(ts) == 3 and ts == sorted(ts)


def test_untracking_purges_goal_evidence_and_switches():
    """Removing a student from the last board must purge everything derived from
    their events, or a re-add mixes stale goal runs into the rebuilt ones."""
    db.tracked_add("u1")
    db.upsert_goal_profile("u1", 7, {"index": 7, "status": "profiled", "ts": 1.0})
    db.record_switch("u1", "casing", "U1", "u1")
    db.tracked_remove("u1")
    assert db.list_goal_profiles("u1", session=None) == []
    assert db.list_switches() == []


def test_goal_evidence_writes_signal_the_states_channel():
    """Goal profiles are written after student_state, so without their own signal
    an open sheet refetches before the newest run's evidence exists."""
    before = db.data_fingerprint()["states"]
    db.upsert_goal_profile("g1", 0, {"index": 0, "status": "profiled", "ts": 1.0})
    assert db.data_fingerprint()["states"] != before


def test_reset_keeps_alerts_that_are_still_open(client, seed_state):
    """Reset hides history, but an alert still holding (an idle student) is the
    student's current state and must stay in the feed."""
    seed_state("o1")
    started = db.now() - timedelta(minutes=5)
    db.create_trigger("o1", "inactive", started, started, None, {"label": "Inactive"})
    client.post("/api/reset/")
    feed = client.get("/api/triggers/").json()["triggers"]
    assert [t["trigger_type"] for t in feed] == ["inactive"]


def test_export_includes_goal_evidence(seed_state):
    seed_state("e1")
    db.upsert_goal_profile("e1", 0, {"index": 0, "status": "profiled", "ts": 1.0})
    names = zipfile.ZipFile(io.BytesIO(db.export_zip_bytes())).namelist()
    assert any(n.endswith("goal_profile.csv") for n in names)


def test_resuming_polling_rebackfills_the_boards_students(client, seed_state):
    """While a board is paused its students aren't fetched, but the shared cursor
    moves on if another board is live. Resuming must pull the gap back in."""
    seed_state("p1")
    db.mark_backfilled("p1")
    client.post("/api/polling/", json={"enabled": False})
    client.post("/api/polling/", json={"enabled": True})
    assert db.tracked_list()[0]["backfilled"] is False
