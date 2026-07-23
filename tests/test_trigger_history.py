"""Trigger history: the per-student grid, and each feed alert carrying the
student's previous trigger (what it was and when)."""
from datetime import timedelta

from app import db


def _fire(sid, ttype, label, minutes_ago, resolved=True, acked=False):
    at = db.now() - timedelta(minutes=minutes_ago)
    db.create_trigger(sid, ttype, started_at=at, last_seen_at=at,
                      resolved_at=at if resolved else None,
                      detail={"label": label, "value": f"v-{ttype}"})
    if acked:
        db.ack_by_student(sid)


def test_history_is_newest_first_and_includes_dismissed():
    _fire("cobra3", "wheel_spin", "Wheel-spinning", 30, acked=True)
    _fire("cobra3", "explorer", "Explorer", 10)
    rows = db.trigger_history("COBRA3")           # case-insensitive lookup
    assert [r["trigger_type"] for r in rows] == ["explorer", "wheel_spin"]
    assert rows[1]["acknowledged"] is True        # dismissed rows still listed


def test_history_endpoint_reports_status(client):
    _fire("bear2", "wheel_spin", "Wheel-spinning", 30, acked=True)
    _fire("bear2", "explorer", "Explorer", 10)
    _fire("bear2", "inactive", "Inactive", 5, resolved=False)
    got = client.get("/api/triggers/history/", params={"studentID": "bear2"}).json()
    assert got["count"] == 3
    assert [r["status"] for r in got["history"]] == ["active", "resolved", "dismissed"]
    assert got["history"][1]["value"] == "v-explorer"


def test_feed_alert_carries_the_previous_trigger(client):
    _fire("cobra3", "wheel_spin", "Wheel-spinning", 20)     # resolved 20m ago: off-feed but history
    _fire("cobra3", "inactive", "Inactive", 1, resolved=False)
    feed = client.get("/api/triggers/").json()["triggers"]
    assert len(feed) == 1                                    # only the open alert shows
    prev = feed[0]["prev"]
    assert prev["trigger_type"] == "wheel_spin"
    assert prev["label"] == "Wheel-spinning"
    assert prev["at"] is not None                            # "at what time" is answered


def test_first_ever_alert_has_no_prev(client):
    _fire("bear2", "inactive", "Inactive", 1, resolved=False)
    feed = client.get("/api/triggers/").json()["triggers"]
    assert feed[0]["prev"] is None
