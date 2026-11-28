"""Lower-level db.py helpers and branches: the write-txn rollback, idempotency
backstops, and small query filters."""

import pytest

from app import db


def test_fired_indices_filters_by_type():
    t = db.now()
    db.create_trigger(
        "s1", "explorer", started_at=t, last_seen_at=t, resolved_at=t, detail={"run_index": 3}
    )
    db.create_trigger(
        "s1", "wheel_spin", started_at=t, last_seen_at=t, resolved_at=t, detail={"run_index": 7}
    )
    assert db.fired_indices("s1", "explorer") == {3}
    assert db.fired_indices("s1", "wheel_spin") == {7}


def test_write_txn_rolls_back_on_error():
    db.tracked_add("s1")
    with pytest.raises(ValueError):
        with db.write_txn() as con:
            con.execute("UPDATE tracked_student SET present=false WHERE studentID='s1'")
            raise ValueError("boom")  # should roll the UPDATE back
    assert db.tracked_list()[0]["present"] is True


def test_log_exists_none_is_false_and_dup_insert_is_idempotent():
    assert db.log_exists(None) is False
    norm = {
        "raw_message": "{}",
        "event_time": db.now(),
        "classCode": "C",
        "eventType": "runProject",
        "studentID": "s1",
        "project": "{}",
        "source_event_id": 77,
    }
    assert db.insert_message_and_log(norm) is True
    # second insert hits the UNIQUE backstop -> IntegrityError caught -> False
    assert db.insert_message_and_log(norm) is False
    assert len(db._query("SELECT 1 FROM vex_log WHERE source_event_id=77")) == 1


def test_mark_backfilled():
    db.tracked_add("s1")
    db.mark_backfilled("s1")
    assert db.tracked_list()[0]["backfilled"] is True


def test_list_student_states_filters_by_class_code():
    db.upsert_student_state("s1", {"classCode": "A", "runs": {}, "episodes": {}})
    db.upsert_student_state("s2", {"classCode": "B", "runs": {}, "episodes": {}})
    only_a = db.list_student_states(class_code="A")
    assert [s["studentID"] for s in only_a] == ["s1"]


def test_cursor_create_save_and_lag():
    from app.pipeline import poller

    cur = poller.get_cursor()
    assert poller.get_cursor_lag(cur) == "n/a"  # no last_event_time yet
    cur.last_event_time = db.now()
    cur.save()
    assert poller.get_cursor_lag(cur).endswith("s")  # now reports a numeric lag
