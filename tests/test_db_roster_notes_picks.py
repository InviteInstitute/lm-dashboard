"""Roster, presence/picked toggles, pick-event history, and notes."""
from app import db


def test_tracked_add_is_idempotent():
    db.tracked_add("s1")
    db.tracked_add("s1")
    rows = db.tracked_list()
    assert [r["studentID"] for r in rows] == ["s1"]


def test_tracked_list_has_data_reflects_state_via_join(seed_state):
    db.tracked_add("with_data")
    db.tracked_add("no_data")
    seed_state("with_data")
    rows = {r["studentID"]: r for r in db.tracked_list()}
    assert rows["with_data"]["has_data"] is True
    assert rows["no_data"]["has_data"] is False
    # the LEFT JOIN must not multiply rows
    assert len(db.tracked_list()) == 2


def test_presence_toggle_persists():
    db.tracked_add("s1")
    db.set_presence("s1", False)
    assert db.tracked_list()[0]["present"] is False
    db.set_presence("s1", True)
    assert db.tracked_list()[0]["present"] is True


def test_pick_sets_and_clears_timestamp():
    db.tracked_add("s1")
    db.set_picked("s1", True)
    row = db.tracked_list()[0]
    assert row["picked"] is True and row["picked_at"] is not None
    db.set_picked("s1", False)
    row = db.tracked_list()[0]
    assert row["picked"] is False and row["picked_at"] is None


def test_pick_event_logs_full_history():
    db.tracked_add("s1")
    db.set_picked("s1", True)
    db.set_picked("s1", False)
    db.set_picked("s1", True)
    rows = db._query("SELECT picked FROM pick_event ORDER BY id")
    assert [r["picked"] for r in rows] == [1, 0, 1]


def test_remove_tracked_cascades_all_student_data(seed_state):
    db.tracked_add("s1")
    seed_state("s1")
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None, {"label": "x"})
    db.insert_message_and_log({
        "raw_message": "{}", "event_time": db.now(), "classCode": "C",
        "eventType": "runProject", "studentID": "s1", "project": "{}",
        "source_event_id": 99,
    })
    db.tracked_remove("s1")
    assert db.tracked_list() == []
    assert db.list_student_states(["s1"]) == []
    assert db._query("SELECT 1 FROM vex_log WHERE studentID='s1'") == []
    assert db._query("SELECT 1 FROM trigger_event WHERE studentID='s1'") == []


def test_add_note_returns_row_and_lists_in_order():
    db.tracked_add("s1")
    n1 = db.add_note("s1", "first note")
    db.add_note("s1", "second note", trigger_id=5, trigger_type="wheel_spin")
    assert n1["id"] is not None and n1["text"] == "first note"
    notes = db.list_notes("s1")
    assert [n["text"] for n in notes] == ["first note", "second note"]
    assert notes[1]["trigger_type"] == "wheel_spin"


def test_notes_isolated_per_student():
    db.add_note("a", "for a")
    db.add_note("b", "for b")
    assert len(db.list_notes("a")) == 1
    assert db.list_notes("a")[0]["text"] == "for a"


def test_meta_set_get_upsert():
    assert db.get_meta("k") is None
    db.set_meta("k", "v1")
    assert db.get_meta("k") == "v1"
    db.set_meta("k", "v2")          # ON CONFLICT update, not duplicate
    assert db.get_meta("k") == "v2"
