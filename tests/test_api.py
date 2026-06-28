"""End-to-end API tests through the FastAPI TestClient -- the contract the
frontend depends on."""
from app import db, config


# --- health / basics -------------------------------------------------------
def test_root_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_basic_auth_gate(client, monkeypatch):
    # When DASHBOARD_USER/PASSWORD are set (remote serving), the whole origin needs
    # the shared Basic login; without them it's open (local dev). Unset by default,
    # so every other test stays open.
    import base64
    from app import auth
    monkeypatch.setattr(auth, "USER", "research")
    monkeypatch.setattr(auth, "PASSWORD", "secret")
    assert client.get("/api/student_states/").status_code == 401          # no creds
    good = base64.b64encode(b"research:secret").decode()
    assert client.get("/api/student_states/",
                      headers={"Authorization": f"Basic {good}"}).status_code == 200
    bad = base64.b64encode(b"research:wrong").decode()
    assert client.get("/api/student_states/",
                      headers={"Authorization": f"Basic {bad}"}).status_code == 401


# --- student_states: light list vs heavy detail (issue #9) -----------------
def test_student_states_list_is_light(client, seed_state):
    seed_state("s1")
    r = client.get("/api/student_states/")
    body = r.json()
    assert body["student_count"] == 1
    student = body["students"][0]
    assert "runs" in student and "episodes" in student     # grid needs the tracks
    assert "current_state" not in student                  # strategy state is gone
    assert "block" not in student                          # but NOT the heavy prompt


def test_student_state_detail_is_heavy(client, seed_state):
    seed_state("s1", playground_prompt="[Active] whenStarted")
    r = client.get("/api/student_states/s1/")
    assert r.status_code == 200
    assert r.json()["block"]["llm_prompt"] == "[Active] whenStarted"


def test_student_state_detail_404_for_unknown(client):
    assert client.get("/api/student_states/ghost/").status_code == 404


def test_student_states_sort_by_recency(client, seed_state):
    from datetime import timedelta
    seed_state("older", last_event_time=db.now() - timedelta(minutes=10))
    seed_state("newer", last_event_time=db.now())
    rows = client.get("/api/student_states/").json()["students"]
    assert rows[0]["studentID"] == "newer"      # most recent activity first


def test_student_states_too_many_ids_rejected(client):
    ids = ",".join(f"s{i}" for i in range(600))
    assert client.get(f"/api/student_states/?students={ids}").status_code == 400


# --- tracked roster --------------------------------------------------------
def test_track_and_untrack_roundtrip(client):
    assert client.post("/api/tracked/", json={"studentID": "s1"}).json() == {"added": "s1"}
    assert client.get("/api/tracked/").json()["count"] == 1
    assert client.post("/api/tracked/", json={"studentID": "s1", "remove": True}).json() == {"removed": "s1"}
    assert client.get("/api/tracked/").json()["count"] == 0


def test_track_requires_student_id(client):
    assert client.post("/api/tracked/", json={"studentID": "  "}).status_code == 400


# --- presence / picked -----------------------------------------------------
def test_presence_and_picked_endpoints(client):
    client.post("/api/tracked/", json={"studentID": "s1"})
    assert client.post("/api/presence/", json={"studentID": "s1", "present": False}).json()["present"] is False
    assert client.post("/api/picked/", json={"studentID": "s1", "picked": True}).json()["picked"] is True
    row = client.get("/api/tracked/").json()["tracked"][0]
    assert row["present"] is False and row["picked"] is True


def test_picked_writes_event_history(client):
    client.post("/api/tracked/", json={"studentID": "s1"})
    client.post("/api/picked/", json={"studentID": "s1", "picked": True})
    client.post("/api/picked/", json={"studentID": "s1", "picked": False})
    assert len(db._query("SELECT 1 FROM pick_event WHERE studentID='s1'")) == 2


# --- notes -----------------------------------------------------------------
def test_notes_post_get_and_validation(client):
    client.post("/api/notes/", json={"studentID": "s1", "text": "watched them"})
    got = client.get("/api/notes/", params={"studentID": "s1"}).json()
    assert got["count"] == 1 and got["notes"][0]["text"] == "watched them"
    assert client.post("/api/notes/", json={"studentID": "s1", "text": "  "}).status_code == 400
    assert client.post("/api/notes/", json={"studentID": "", "text": "x"}).status_code == 400
    assert client.get("/api/notes/").status_code == 400      # missing studentID


def test_note_can_link_to_trigger(client):
    client.post("/api/notes/", json={"studentID": "s1", "text": "during alert",
                                     "trigger_id": 9, "trigger_type": "wheel_spin"})
    assert client.get("/api/notes/", params={"studentID": "s1"}).json()["notes"][0]["trigger_type"] == "wheel_spin"


# --- polling toggle --------------------------------------------------------
def test_polling_defaults_on_and_toggles(client):
    assert client.get("/api/polling/").json()["enabled"] is True
    assert client.post("/api/polling/", json={"enabled": False}).json()["enabled"] is False
    assert client.get("/api/polling/").json()["enabled"] is False
    assert db.get_meta("polling_enabled") == "0"


# --- trigger config --------------------------------------------------------
def test_trigger_config_toggle_and_unknown_type(client):
    cfg = client.get("/api/triggers/config/").json()
    assert cfg["enabled"] == {"wheel_spin": True, "resilience": True, "inactive": True,
                              "explorer": True, "iterative": True}
    client.post("/api/triggers/config/", json={"trigger_type": "inactive", "enabled": False})
    assert client.get("/api/triggers/config/").json()["enabled"]["inactive"] is False
    assert client.post("/api/triggers/config/",
                       json={"trigger_type": "nope", "enabled": False}).status_code == 400
    # re-enable it again (the discard path)
    client.post("/api/triggers/config/", json={"trigger_type": "inactive", "enabled": True})
    assert client.get("/api/triggers/config/").json()["enabled"]["inactive"] is True


# --- triggers feed + ack ---------------------------------------------------
def test_triggers_feed_and_ack(client):
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None,
                      {"label": "Wheel-spinning", "value": "3 re-runs"})
    feed = client.get("/api/triggers/").json()
    assert feed["active_count"] == 1
    tid = feed["triggers"][0]["id"]
    assert client.post("/api/triggers/ack/", json={"id": tid}).json()["acknowledged"] == 1
    assert client.get("/api/triggers/").json()["active_count"] == 0


def test_ack_requires_id_or_student(client):
    assert client.post("/api/triggers/ack/", json={}).status_code == 400


def test_ack_by_student_via_api(client):
    db.create_trigger("s1", "wheel_spin", db.now(), db.now(), None, {})
    db.create_trigger("s1", "inactive", db.now(), db.now(), None, {})
    assert client.post("/api/triggers/ack/", json={"studentID": "s1"}).json()["acknowledged"] == 2


def test_student_states_filtered_by_class_code(client, seed_state):
    seed_state("a", classCode="A")
    seed_state("b", classCode="B")
    rows = client.get("/api/student_states/?classCode=A").json()["students"]
    assert [s["studentID"] for s in rows] == ["a"]


def test_presence_and_picked_require_student_id(client):
    assert client.post("/api/presence/", json={"studentID": "", "present": True}).status_code == 400
    assert client.post("/api/picked/", json={"studentID": "  ", "picked": True}).status_code == 400


# --- export / reset (redirect output dir to a tmp path) --------------------
def test_export_writes_snapshot(client, seed_state, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    seed_state("s1")
    r = client.post("/api/export/")
    assert r.status_code == 200 and r.json()["exported"] is True
    assert (tmp_path / "exports").exists()


def test_reset_backs_up_then_wipes(client, seed_state, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    db.tracked_add("s1")
    seed_state("s1")
    db.add_note("s1", "keep me in the backup")

    r = client.post("/api/reset/")
    assert r.json()["reset"] is True and r.json()["backup"]
    # data wiped, roster kept
    assert client.get("/api/student_states/").json()["student_count"] == 0
    assert client.get("/api/tracked/").json()["count"] == 1
    # the note survived into the backup CSV
    import os
    note_csv = os.path.join(r.json()["backup"], "note.csv")
    with open(note_csv) as f:
        assert "keep me in the backup" in f.read()
