"""The trigger evaluator: the one sustained trigger (inactive) sustain/resolve,
the disable flag, and the re-alert rotation. The four momentary edit-distance
triggers fire from the worker; see test_workers.py and test_run_triggers.py."""
from datetime import timedelta

from app import db
from app.pipeline import triggers


def _state(sid, last_event_time=None):
    db.upsert_student_state(sid, {"last_event_time": last_event_time})


def test_inactive_opens_when_idle_and_resolves_on_activity():
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    _state("s1", last_event_time=old)
    triggers.evaluate()
    assert db.current_open_trigger("s1", "inactive") is not None

    _state("s1", last_event_time=db.now())          # just acted -> no longer idle
    triggers.evaluate()
    assert db.current_open_trigger("s1", "inactive") is None


def test_inactive_fires_only_past_240s():
    assert triggers.INACTIVE_TRIGGER_SECONDS == 240
    recent = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS - 30)
    _state("fresh", last_event_time=recent)
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    _state("idle", last_event_time=old)

    triggers.evaluate()
    assert db.current_open_trigger("fresh", "inactive") is None
    assert db.current_open_trigger("idle", "inactive") is not None


def test_disabled_type_does_not_fire_and_clears_open_rows():
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    _state("s1", last_event_time=old)
    triggers.evaluate()
    assert db.current_open_trigger("s1", "inactive") is not None

    db.set_meta("disabled_triggers", "inactive")
    triggers.evaluate()
    # disabling a sustained type resolves its open row within a tick
    assert db.current_open_trigger("s1", "inactive") is None


def test_sustained_trigger_is_not_duplicated_across_ticks():
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    _state("s1", last_event_time=old)
    triggers.evaluate()
    triggers.evaluate()
    triggers.evaluate()
    rows = db._query("SELECT 1 FROM trigger_event WHERE studentID='s1' "
                     "AND trigger_type='inactive' AND resolved_at IS NULL")
    assert len(rows) == 1


def test_held_trigger_touch_is_throttled():
    """A held inactive row isn't rewritten every tick: last_seen_at only refreshes
    once past TRIGGER_TOUCH_THROTTLE_S, so the sweep's per-tick write load doesn't
    scale with the number of idle students."""
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    _state("s1", last_event_time=old)
    triggers.evaluate()
    seen1 = db.current_open_trigger("s1", "inactive")["last_seen_at"]

    triggers.evaluate()   # immediate re-tick -> within the throttle window, no write
    assert db.current_open_trigger("s1", "inactive")["last_seen_at"] == seen1

    # Backdate last_seen_at beyond the throttle window; now a tick should refresh it.
    backdated = seen1 - timedelta(seconds=triggers.TRIGGER_TOUCH_THROTTLE_S + 5)
    ev_id = db.current_open_trigger("s1", "inactive")["id"]
    db._execute("UPDATE trigger_event SET last_seen_at=? WHERE id=?", (db.dt_to_db(backdated), ev_id))
    triggers.evaluate()
    assert db.current_open_trigger("s1", "inactive")["last_seen_at"] > backdated


def test_acked_but_still_idle_rotates_after_re_alert_window():
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    _state("s1", last_event_time=old)
    triggers.evaluate()
    ev = db.current_open_trigger("s1", "inactive")
    db.ack_by_id(ev["id"])

    # backdate the open row's start beyond the re-alert window, then re-evaluate
    past = db.dt_to_db(db.now() - timedelta(seconds=triggers.RE_ALERT_SECONDS + 10))
    db._execute("UPDATE trigger_event SET started_at=? WHERE id=?", (past, ev["id"]))
    triggers.evaluate()

    fresh = db.current_open_trigger("s1", "inactive")
    assert fresh is not None and fresh["id"] != ev["id"]   # a new, unacked row surfaced
    assert fresh["acknowledged"] is False
