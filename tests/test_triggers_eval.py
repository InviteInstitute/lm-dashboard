"""The trigger evaluator: wheel_spin + inactive sustain/resolve, the disable
flag, and the re-alert rotation. (big_change no longer lives here -- it fires
from the worker; see test_workers.py.)"""
from datetime import timedelta

from app import db
from app.pipeline import triggers


def _state(sid, current_state=None, last_event_time=None, consecutive_stuck=0, runs=None):
    db.upsert_student_state(sid, {
        "current_state": current_state,
        "consecutive_stuck": consecutive_stuck,
        "last_event_time": last_event_time,
        "runs": runs or {"runs": [], "obs_labels": {}},
    })


def test_wheel_spin_opens_when_stuck_and_resolves_when_not():
    _state("s1", current_state=triggers.WHEEL_SPIN_STATE)
    triggers.evaluate()
    assert db.current_open_trigger("s1", "wheel_spin") is not None

    _state("s1", current_state=1)               # no longer stuck
    triggers.evaluate()
    assert db.current_open_trigger("s1", "wheel_spin") is None


def test_inactive_fires_only_past_threshold():
    recent = db.now() - timedelta(seconds=triggers.INACTIVE_SECONDS - 30)
    _state("fresh", current_state=1, last_event_time=recent)
    old = db.now() - timedelta(seconds=triggers.INACTIVE_SECONDS + 30)
    _state("idle", current_state=1, last_event_time=old)

    triggers.evaluate()
    assert db.current_open_trigger("fresh", "inactive") is None
    assert db.current_open_trigger("idle", "inactive") is not None


def test_disabled_type_does_not_fire_and_clears_open_rows():
    _state("s1", current_state=triggers.WHEEL_SPIN_STATE)
    triggers.evaluate()
    assert db.current_open_trigger("s1", "wheel_spin") is not None

    db.set_meta("disabled_triggers", "wheel_spin")
    triggers.evaluate()
    # disabling a sustained type resolves its open row within a tick
    assert db.current_open_trigger("s1", "wheel_spin") is None


def test_sustained_trigger_is_not_duplicated_across_ticks():
    _state("s1", current_state=triggers.WHEEL_SPIN_STATE)
    triggers.evaluate()
    triggers.evaluate()
    triggers.evaluate()
    rows = db._query("SELECT 1 FROM trigger_event WHERE studentID='s1' "
                     "AND trigger_type='wheel_spin' AND resolved_at IS NULL")
    assert len(rows) == 1


def test_acked_but_still_stuck_rotates_after_re_alert_window():
    _state("s1", current_state=triggers.WHEEL_SPIN_STATE)
    triggers.evaluate()
    ev = db.current_open_trigger("s1", "wheel_spin")
    db.ack_by_id(ev["id"])

    # backdate the open row's start beyond the re-alert window, then re-evaluate
    past = db.dt_to_db(db.now() - timedelta(seconds=triggers.RE_ALERT_SECONDS + 10))
    db._execute("UPDATE trigger_event SET started_at=? WHERE id=?", (past, ev["id"]))
    triggers.evaluate()

    fresh = db.current_open_trigger("s1", "wheel_spin")
    assert fresh is not None and fresh["id"] != ev["id"]   # a new, unacked row surfaced
    assert fresh["acknowledged"] is False
