"""Failed-write outbox: parked researcher inputs must survive everything."""

import json

from app import db


def test_record_and_list_roundtrip():
    db.record_outbox("note on cobra3", json.dumps({"text": "seen switching"}), "timeout")
    rows = db.list_outbox()
    assert len(rows) == 1
    assert rows[0]["op"] == "note on cobra3"
    assert json.loads(rows[0]["payload"])["text"] == "seen switching"
    assert rows[0]["error"] == "timeout"


def test_outbox_api_stores_and_lists(client):
    body = {
        "op": "present: cobra3",
        "payload": {"studentID": "cobra3", "present": True},
        "error": "Network Error",
    }
    assert client.post("/api/outbox/", json=body).json() == {"stored": True}
    got = client.get("/api/outbox/").json()
    assert got["count"] == 1
    assert got["outbox"][0]["op"] == "present: cobra3"
    assert json.loads(got["outbox"][0]["payload"])["studentID"] == "cobra3"


def test_reset_spares_the_outbox():
    db.record_outbox("pick: bear2", None, "locked")
    db.reset_workspace()
    assert len(db.list_outbox()) == 1  # parked inputs survive a board reset


def test_newest_first_ordering():
    db.record_outbox("first", None, None)
    db.record_outbox("second", None, None)
    assert [r["op"] for r in db.list_outbox()] == ["second", "first"]
