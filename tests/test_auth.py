"""Researcher auth: the session gate, login/logout, and the /api/me probe."""
from app import auth, db


def test_healthz_is_open(anon_client):
    assert anon_client.get("/healthz").status_code == 200


def test_api_requires_login(anon_client):
    assert anon_client.get("/api/student_states/").status_code == 401
    assert anon_client.get("/api/me/").status_code == 401


def test_login_rejects_wrong_password(anon_client):
    db.upsert_researcher("alice", auth.hash_password("rightpw"))
    r = anon_client.post("/api/login/", json={"username": "alice", "password": "nope"})
    assert r.status_code == 401
    assert anon_client.get("/api/student_states/").status_code == 401


def test_login_grants_access_and_me(anon_client):
    db.upsert_researcher("alice", auth.hash_password("rightpw"))
    # Usernames are case-insensitive.
    r = anon_client.post("/api/login/", json={"username": "Alice", "password": "rightpw"})
    assert r.status_code == 200 and r.json()["username"] == "alice"
    assert anon_client.get("/api/student_states/").status_code == 200
    me = anon_client.get("/api/me/")
    assert me.status_code == 200 and me.json()["username"] == "alice"


def test_logout_clears_the_session(anon_client):
    db.upsert_researcher("alice", auth.hash_password("rightpw"))
    anon_client.post("/api/login/", json={"username": "alice", "password": "rightpw"})
    assert anon_client.post("/api/logout/").status_code == 200
    assert anon_client.get("/api/me/").status_code == 401


def test_upsert_resets_password(anon_client):
    db.upsert_researcher("alice", auth.hash_password("oldpw"))
    db.upsert_researcher("alice", auth.hash_password("newpw"))  # same username -> reset
    assert anon_client.post("/api/login/", json={"username": "alice", "password": "oldpw"}).status_code == 401
    assert anon_client.post("/api/login/", json={"username": "alice", "password": "newpw"}).status_code == 200


def test_password_hash_roundtrips():
    h = auth.hash_password("hunter2")
    assert h != "hunter2"
    assert auth.verify_password(h, "hunter2") is True
    assert auth.verify_password(h, "wrong") is False
