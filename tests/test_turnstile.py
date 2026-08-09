"""The Cloudflare Turnstile bot gate over /api/* (see app/turnstile.py), which
replaced HTTP Basic Auth: the dashboard is public, this only keeps bots off."""

from app.turnstile import COOKIE_NAME, cookie_is_valid, sign_cookie


def test_healthz_is_open(anon_client):
    assert anon_client.get("/healthz").status_code == 200


def test_missing_cookie_is_gated(anon_client):
    r = anon_client.get("/api/student_states/")
    assert r.status_code == 403
    assert r.json()["error"] == "turnstile_required"


def test_valid_cookie_passes(client):
    assert client.get("/api/student_states/").status_code == 200


def test_tampered_cookie_is_gated(anon_client):
    anon_client.cookies.set(COOKIE_NAME, sign_cookie() + "x")
    r = anon_client.get("/api/student_states/")
    assert r.status_code == 403


def test_verify_endpoint_sets_cookie_on_success(anon_client, monkeypatch):
    monkeypatch.setattr("app.main.verify_turnstile", _fake_verify(True))
    r = anon_client.post("/api/turnstile/verify/", json={"token": "whatever"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.cookies.get(COOKIE_NAME)
    # The cookie just minted is one the gate itself accepts.
    assert anon_client.get("/api/student_states/").status_code == 200


def test_verify_endpoint_rejects_failed_challenge(anon_client, monkeypatch):
    monkeypatch.setattr("app.main.verify_turnstile", _fake_verify(False))
    r = anon_client.post("/api/turnstile/verify/", json={"token": "whatever"})
    assert r.status_code == 403
    assert not r.cookies.get(COOKIE_NAME)


def test_cookie_sign_roundtrip():
    value = sign_cookie()
    assert cookie_is_valid(value) is True
    assert cookie_is_valid(value + "tampered") is False
    assert cookie_is_valid(None) is False


def _fake_verify(result):
    async def _verify(token, remote_ip):
        return result

    return _verify
