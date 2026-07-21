"""SSE live stream: the change fingerprint, the pure channel diff, and the
endpoint handshake. The live loop itself isn't exercised here (it never ends by
design); `once=1` returns just the hello so the test can't block on it."""
from app import db
from app.main import _changed_channels


def test_changed_channels_first_tick_is_never_a_change():
    assert _changed_channels(None, {"states": "a", "roster": "b"}) == []


def test_changed_channels_lists_only_the_channels_that_moved():
    prev = {"states": "1", "roster": "1", "triggers": "1", "switches": "1"}
    cur = {"states": "1", "roster": "2", "triggers": "1", "switches": "9"}
    assert sorted(_changed_channels(prev, cur)) == ["roster", "switches"]


def test_fingerprint_moves_when_roster_changes_and_leaves_others_still():
    before = db.data_fingerprint()
    db.tracked_add("cobra3")
    after = db.data_fingerprint()
    assert after["roster"] != before["roster"]
    assert after["states"] == before["states"]        # unrelated channel unchanged
    assert after["triggers"] == before["triggers"]


def test_fingerprint_moves_when_a_switch_is_recorded():
    before = db.data_fingerprint()
    db.record_switch("cobra3", "class", "FPFVDH", "AFURRR")
    after = db.data_fingerprint()
    assert after["switches"] != before["switches"]


def test_fingerprint_moves_when_presence_toggles():
    db.tracked_add("cobra3")
    before = db.data_fingerprint()
    db.set_presence("cobra3", False)
    after = db.data_fingerprint()
    assert after["roster"] != before["roster"]


def test_stream_endpoint_opens_with_hello(client):
    r = client.get("/api/stream/?once=1")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: hello" in r.text
