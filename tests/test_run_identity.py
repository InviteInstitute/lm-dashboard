"""Run identity across backfills, daemon restarts and board resets.

A run's number is its position in the worker's replay window, so it is only
meaningful inside one daemon session. These tests pin down that (1) a backfill
numbers runs oldest-first, (2) a restart's new session never overwrites or hides
behind an earlier session's goal evidence or alert dedupe, and (3) a board reset
hides everything on the student tile from before it, together.
"""

import json
from datetime import UTC, datetime, timedelta

from app import db
from app.pipeline import poller, workers
from app.pipeline.workers import StudentWorker

NS = 'xmlns="https://developers.google.com/blockly/xml"'
CC_XML = (
    f'<xml {NS}><block type="pg_events_when_started" id="h"><next>'
    '<block type="pg_drivetrain_drive_for" id="d">'
    '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">{n}</field></shadow></value>'
    "</block></next></block></xml>"
)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _run(sid, i, at):
    xml = CC_XML.replace("{n}", str(100 + 50 * i))
    content = {"project": {"workspace": xml}, "playground": "CasteCrasherPlus"}
    return {
        "studentID": sid,
        "classCode": "C1",
        "eventType": "runProject",
        "raw_message": json.dumps(content),
        "project": {"workspace": xml},
        "source_event_id": 1000 + i,
        "event_time": at,
    }


def _prod_ev(i, sid, at):
    """A prod-API-shaped runProject event, as page_student returns it."""
    xml = CC_XML.replace("{n}", str(100 + 50 * i))
    return {
        "id": 1000 + i,
        "studentID": sid,
        "classCode": "C1",
        "eventType": "runProject",
        "project": json.dumps({"workspace": xml}),
        "raw_message": json.dumps(
            {"project": {"workspace": xml}, "playground": "CasteCrasherPlus"}
        ),
        "received_at": at.isoformat().replace("+00:00", "Z"),
    }


class _PagedClient:
    def __init__(self, pages):
        self.pages = pages

    def page_student(self, sid, limit, offset):
        idx = offset // limit
        return self.pages[idx] if idx < len(self.pages) else []


# --- (1) backfill order ---------------------------------------------------------
def test_backfill_numbers_runs_oldest_first():
    """page_student is newest-first. Routing each event as it lands fed the
    worker newest-first, so run 0 was the NEWEST run and every edit distance and
    goal profile was computed over a reversed history."""
    db.tracked_add("bf1")
    times = [T0 + timedelta(minutes=m) for m in (0, 5, 10)]
    newest_first = [_prod_ev(i, "bf1", t) for i, t in reversed(list(enumerate(times)))]
    poller.backfill_student(_PagedClient([newest_first]), "bf1")
    workers.get_worker("bf1").recompute_and_write()

    runs = db.list_student_states(["bf1"])[0]["runs"]["runs"]
    stamps = [r["ts"] for r in runs]
    assert len(stamps) == 3
    assert stamps == sorted(stamps), "runs must be numbered oldest-first"
    profs = db.list_goal_profiles("bf1")
    assert [p["ts"] for p in profs] == sorted(p["ts"] for p in profs)


# --- (2) restarts -----------------------------------------------------------------
def _session(since):
    workers.reset()
    workers.start_session(since)


def test_a_new_session_never_overwrites_an_earlier_sessions_goal_runs():
    s1, s2 = T0, T0 + timedelta(hours=2)
    _session(s1)
    w = StudentWorker("rs1")
    for i in range(3):
        w.ingest(_run("rs1", i, s1 + timedelta(minutes=i)))
    w.recompute_and_write()
    before = {p["ts"] for p in db.list_goal_profiles("rs1")}
    assert len(before) == 3

    # Restart: a new session replays only its own events, so its first run is
    # run 0 again. It must not replace session one's run 0.
    _session(s2)
    w2 = StudentWorker("rs1")
    w2.ingest(_run("rs1", 7, s2 + timedelta(minutes=1)))
    w2.recompute_and_write()

    everything = db.list_goal_profiles("rs1", session=None)
    assert before <= {p["ts"] for p in everything}, "an earlier session's run was overwritten"
    assert len(everything) == 4
    # The live view is the current session only, joined to its own runs.
    current = db.list_goal_profiles("rs1")
    assert [p["index"] for p in current] == [0]


def test_alert_dedupe_is_per_session():
    """A run index that fired in an earlier session must not block the same index
    from alerting in a later one."""
    _session(T0)
    db.create_trigger(
        "rs2",
        "wheel_spin",
        started_at=T0,
        last_seen_at=T0,
        resolved_at=T0,
        detail={"run_index": 3, "session": workers.session_key()},
    )
    assert db.fired_indices("rs2", "wheel_spin", session=workers.session_key()) == {3}
    _session(T0 + timedelta(hours=2))
    assert db.fired_indices("rs2", "wheel_spin", session=workers.session_key()) == set()


# --- (3) board reset ---------------------------------------------------------------
def test_reset_hides_everything_on_the_tile_from_before_it(client, seed_state):
    now = db.now()
    before, after = now - timedelta(minutes=10), now + timedelta(minutes=10)
    seed_state(
        "rz1",
        runs={
            "runs": [
                {"index": 0, "edit_distance": None, "ts": before.timestamp()},
                {"index": 1, "edit_distance": 4, "ts": after.timestamp()},
            ],
            "run_count": 2,
        },
        episodes={
            "episodes": [
                {
                    "start_idx": 0,
                    "end_idx": 3,
                    "event_count": 3,
                    "episode_type": "CODE",
                    "start_ts": before.timestamp(),
                    "end_ts": before.timestamp() + 5,
                },
                {
                    "start_idx": 3,
                    "end_idx": 5,
                    "event_count": 2,
                    "episode_type": "RUN",
                    "start_ts": after.timestamp(),
                    "end_ts": after.timestamp() + 5,
                },
            ],
            "pauses": [{"after_idx": 2, "episode_type": "INACTIVE_PAUSE", "duration": 90}],
            "event_count": 5,
        },
    )
    for at in (before, after):
        db.create_trigger("rz1", "explorer", at, at, at, {"label": "Explorer", "run_index": 0})
    db.upsert_goal_profile("rz1", 0, {"index": 0, "status": "profiled", "ts": before.timestamp()})
    db.upsert_goal_profile("rz1", 1, {"index": 1, "status": "profiled", "ts": after.timestamp()})

    assert client.post("/api/reset/").json()["reset"] is True

    card = client.get("/api/student_states/").json()["students"][0]
    assert [r["index"] for r in card["runs"]["runs"]] == [1]
    assert card["run_count"] == 1
    assert [e["episode_type"] for e in card["episodes"]["episodes"]] == ["RUN"]
    assert card["episodes"]["pauses"] == []
    assert card["event_count"] == 2

    detail = client.get("/api/student_states/rz1/").json()
    assert [g["index"] for g in detail["goal_runs"]] == [1]
    history = client.get("/api/triggers/history/", params={"studentID": "rz1"}).json()
    assert history["count"] == 1
