"""Workspace tenancy (Phase 2): the roster/presence/picked slice is isolated
per workspace, and the shared per-student mirror is only purged when no workspace
tracks the student any more."""
from app import auth, db


def test_roster_is_isolated_per_workspace():
    a = db.create_workspace("A")
    b = db.create_workspace("B")
    db.tracked_add("cobra3", workspace_id=a)
    db.tracked_add("viper1", workspace_id=a)
    db.tracked_add("cobra3", workspace_id=b)          # same student, other board
    ra = {r["studentID"] for r in db.tracked_list(workspace_id=a)}
    rb = {r["studentID"] for r in db.tracked_list(workspace_id=b)}
    assert ra == {"cobra3", "viper1"}
    assert rb == {"cobra3"}


def test_presence_and_picked_are_isolated():
    a = db.create_workspace("A")
    b = db.create_workspace("B")
    db.tracked_add("cobra3", workspace_id=a)
    db.tracked_add("cobra3", workspace_id=b)
    db.set_presence("cobra3", False, workspace_id=a)
    db.set_picked("cobra3", True, workspace_id=b)
    la = {r["studentID"]: r for r in db.tracked_list(workspace_id=a)}["cobra3"]
    lb = {r["studentID"]: r for r in db.tracked_list(workspace_id=b)}["cobra3"]
    assert la["present"] is False and la["picked"] is False   # A's view
    assert lb["present"] is True and lb["picked"] is True      # B's view


def test_remove_keeps_shared_mirror_until_last_workspace_untracks():
    a = db.create_workspace("A")
    b = db.create_workspace("B")
    db.tracked_add("cobra3", workspace_id=a)
    db.tracked_add("cobra3", workspace_id=b)
    db.insert_message_and_log({
        "raw_message": "{}", "event_time": db.now(), "classCode": "C1",
        "eventType": "runProject", "studentID": "cobra3", "project": "{}",
        "source_event_id": 1})
    db.upsert_student_state("cobra3", {"run_count": 1})

    db.tracked_remove("cobra3", workspace_id=a)               # A untracks
    assert db.log_exists(1) is True                           # B still tracks -> kept
    assert db.list_student_states(["cobra3"])

    db.tracked_remove("cobra3", workspace_id=b)               # last one untracks
    assert db.log_exists(1) is False                         # now purged
    assert not db.list_student_states(["cobra3"])


def test_student_states_scoped_to_workspace_roster():
    a = db.create_workspace("A")
    b = db.create_workspace("B")
    db.tracked_add("cobra3", workspace_id=a)
    db.tracked_add("viper1", workspace_id=b)
    db.upsert_student_state("cobra3", {"run_count": 1})
    db.upsert_student_state("viper1", {"run_count": 1})
    assert {s["studentID"] for s in db.list_student_states(workspace_id=a)} == {"cobra3"}
    assert {s["studentID"] for s in db.list_student_states(workspace_id=b)} == {"viper1"}


def test_creating_a_researcher_provisions_a_workspace():
    rid = db.upsert_researcher("dr_x", auth.hash_password("pw"))
    ws = db.workspace_ids_for_researcher(rid)
    assert len(ws) == 1
    # Password reset (re-upsert) doesn't create a second workspace.
    db.upsert_researcher("dr_x", auth.hash_password("pw2"))
    assert db.workspace_ids_for_researcher(rid) == ws
