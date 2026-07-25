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


def test_workspace_for_client_key_is_stable():
    before = db._query("SELECT COUNT(*) AS c FROM workspace")[0]["c"]
    a = db.workspace_for_client_key("k1")
    b = db.workspace_for_client_key("k1")   # same key -> same board
    b2 = db.workspace_for_client_key("k1")  # ... and repeat calls create NO new rows
    c = db.workspace_for_client_key("k2")   # new key -> new board
    assert a == b == b2 and a != c
    after = db._query("SELECT COUNT(*) AS c FROM workspace")[0]["c"]
    assert after - before == 2              # exactly k1 + k2, not one per call


def _browser(board_id):
    """A TestClient that has solved Turnstile, bound to a browser key via the
    X-Board-Id header."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.turnstile import COOKIE_NAME, sign_cookie
    c = TestClient(app, base_url="https://testserver")
    c.headers["X-Board-Id"] = board_id
    c.cookies.set(COOKIE_NAME, sign_cookie())
    return c


def test_per_browser_boards_isolated():
    """The device-isolation model: each browser (distinct localStorage board_id)
    gets its own isolated board -- the dashboard is public, with no login step."""
    b1 = _browser("browser-aaaa")
    b2 = _browser("browser-bbbb")
    b1.post("/api/tracked/", json={"studentID": "cobra3"})
    assert b1.get("/api/tracked/").json()["count"] == 1
    assert b2.get("/api/tracked/").json()["count"] == 0     # other browser, own board

    # The same browser key returns to the same board on a later visit.
    b1_again = _browser("browser-aaaa")
    assert b1_again.get("/api/tracked/").json()["count"] == 1


def test_api_isolation_between_two_boards():
    """End-to-end: two boards watching the SAME student see the same underlying
    state but fully isolated rosters, notes, and presence."""
    ca, cb = _browser("board-a"), _browser("board-b")
    for c in (ca, cb):
        c.post("/api/tracked/", json={"studentID": "cobra3"})
    db.upsert_student_state("cobra3", {"run_count": 3})   # shared per-student state

    # Both boards see the shared student's state ...
    assert ca.get("/api/student_states/").json()["student_count"] == 1
    assert cb.get("/api/student_states/").json()["student_count"] == 1

    # ... but a note A writes is invisible to B.
    ca.post("/api/notes/", json={"studentID": "cobra3", "text": "A only"})
    assert ca.get("/api/notes/?studentID=cobra3").json()["count"] == 1
    assert cb.get("/api/notes/?studentID=cobra3").json()["count"] == 0

    # ... and presence toggled on A doesn't move B's board.
    ca.post("/api/presence/", json={"studentID": "cobra3", "present": False})
    a_row = next(t for t in ca.get("/api/tracked/").json()["tracked"] if t["studentID"] == "cobra3")
    b_row = next(t for t in cb.get("/api/tracked/").json()["tracked"] if t["studentID"] == "cobra3")
    assert a_row["present"] is False and b_row["present"] is True

    # B untracking cobra3 leaves A's roster (and the shared state) intact.
    cb.post("/api/tracked/", json={"studentID": "cobra3", "remove": True})
    assert cb.get("/api/tracked/").json()["count"] == 0
    assert ca.get("/api/tracked/").json()["count"] == 1
    assert ca.get("/api/student_states/").json()["student_count"] == 1
