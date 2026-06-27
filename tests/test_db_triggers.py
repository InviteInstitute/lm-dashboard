"""Trigger-event DB helpers: open/touch/resolve/ack and the big_change seed."""
from app import db


def test_create_then_current_open_trigger():
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None, {"label": "Wheel"})
    ev = db.current_open_trigger("s1", "wheel_spin")
    assert ev is not None and ev["acknowledged"] is False
    assert ev["detail"]["label"] == "Wheel"


def test_resolved_trigger_is_not_open():
    db.create_trigger("s1", "inactive", db.now(), db.now(), db.now(), {"label": "Idle"})
    assert db.current_open_trigger("s1", "inactive") is None


def test_resolve_trigger_sets_resolved_at():
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None, {})
    ev = db.current_open_trigger("s1", "wheel_spin")
    db.resolve_trigger(ev["id"], db.now())
    assert db.current_open_trigger("s1", "wheel_spin") is None


def test_ack_by_id_and_by_student():
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None, {})
    ev = db.current_open_trigger("s1", "wheel_spin")
    assert db.ack_by_id(ev["id"]) == 1

    db.create_trigger("s2", "wheel_spin", db.now(), db.now(), None, {})
    db.create_trigger("s2", "inactive", db.now(), db.now(), None, {})
    assert db.ack_by_student("s2") == 2          # both open rows for s2
    assert db.ack_by_student("s2") == 0          # idempotent: nothing left open


def test_triggers_feed_filters_acked_and_old_resolved():
    from datetime import timedelta
    now = db.now()
    db.create_trigger("active", "wheel_spin", now, now, None, {})            # active
    db.create_trigger("recent", "inactive", now, now, now, {})              # just resolved
    old = now - timedelta(hours=1)
    db.create_trigger("stale", "inactive", old, old, old, {})              # resolved long ago
    acked = "acked"
    db.create_trigger(acked, "wheel_spin", now, now, None, {})
    db.ack_by_student(acked)

    cutoff = now - timedelta(seconds=120)
    feed = {t["studentID"] for t in db.triggers_feed(cutoff)}
    assert "active" in feed and "recent" in feed
    assert "stale" not in feed and "acked" not in feed


def test_fired_indices_seeds_from_db():
    db.create_trigger("s1", "explorer", db.now(), db.now(), db.now(),
                      {"label": "Explorer", "run_index": 3})
    db.create_trigger("s1", "explorer", db.now(), db.now(), db.now(),
                      {"label": "Explorer", "run_index": 7})
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None,
                      {"run_index": 5})                                  # different type
    assert db.fired_indices("s1", "explorer") == {3, 7}
    assert db.fired_indices("nobody", "explorer") == set()
