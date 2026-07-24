"""Researcher auth: the browser-native HTTP Basic gate over the whole origin."""
import base64

from app import auth, db
from fastapi.testclient import TestClient
from app.main import app as fastapi_app


def _basic(username, password):
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def test_healthz_is_open(anon_client):
    assert anon_client.get("/healthz").status_code == 200


def test_missing_credentials_prompt_the_browser(anon_client):
    r = anon_client.get("/api/student_states/")
    assert r.status_code == 401
    # WWW-Authenticate: Basic is what makes the browser show its native dialog.
    assert r.headers.get("www-authenticate", "").lower().startswith("basic")


def test_wrong_credentials_are_rejected(anon_client):
    db.upsert_researcher("alice", auth.hash_password("rightpw"))
    r = anon_client.get("/api/student_states/", headers={"Authorization": _basic("alice", "nope")})
    assert r.status_code == 401


def test_valid_credentials_pass_and_me_reports_the_user(anon_client):
    db.upsert_researcher("alice", auth.hash_password("rightpw"))
    hdr = {"Authorization": _basic("Alice", "rightpw")}   # username is case-insensitive
    assert anon_client.get("/api/student_states/", headers=hdr).status_code == 200
    me = anon_client.get("/api/me/", headers=hdr)
    assert me.status_code == 200 and me.json()["username"] == "alice"


def test_password_hash_roundtrips():
    h = auth.hash_password("hunter2")
    assert h != "hunter2"
    assert auth.verify_password(h, "hunter2") is True
    assert auth.verify_password(h, "wrong") is False


def test_auth_header_is_cached_and_wrong_creds_rejected():
    # The same header resolves once and is then served from cache; a wrong password
    # is a different header (never cached), so it's verified fresh and rejected.
    db.upsert_researcher("bob", auth.hash_password("pw1"))
    auth._auth_cache.clear()
    assert auth._resolve_basic(_basic("bob", "pw1")) is not None   # verified + cached
    assert auth._resolve_basic(_basic("bob", "pw1")) is not None   # from cache
    assert auth._resolve_basic(_basic("bob", "wrong")) is None
