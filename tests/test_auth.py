"""Password hashing helpers in app/auth.py. The HTTP gate itself is Turnstile now
(see test_turnstile.py) -- this module's argon2 helpers stay in place unwired
for scripts/create_researcher.py and any future per-account login."""
from app import auth


def test_password_hash_roundtrips():
    h = auth.hash_password("hunter2")
    assert h != "hunter2"
    assert auth.verify_password(h, "hunter2") is True
    assert auth.verify_password(h, "wrong") is False


def test_auth_header_is_cached_and_wrong_creds_rejected():
    # The same header resolves once and is then served from cache; a wrong password
    # is a different header (never cached), so it's verified fresh and rejected.
    from app import db
    db.upsert_researcher("bob", auth.hash_password("pw1"))
    auth._auth_cache.clear()

    def _basic(username, password):
        import base64
        return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    assert auth._resolve_basic(_basic("bob", "pw1")) is not None   # verified + cached
    assert auth._resolve_basic(_basic("bob", "pw1")) is not None   # from cache
    assert auth._resolve_basic(_basic("bob", "wrong")) is None
