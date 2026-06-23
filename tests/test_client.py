"""The prod REST client, with requests mocked out -- auth, token caching, the
401 re-auth retry, paging, and credential loading."""
import pytest

from app.pipeline import client as client_mod
from app.pipeline.client import ProdClient, ProdClientError


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    """Scriptable session: token POST returns a token; GETs come from a queue."""
    def __init__(self, token_status=200, get_responses=None):
        self.token_status = token_status
        self.get_responses = list(get_responses or [])
        self.posts = []
        self.gets = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return FakeResp(self.token_status, {"token": "TKN"})

    def get(self, url, headers=None, params=None, timeout=None):
        self.gets.append((url, params, headers))
        return self.get_responses.pop(0)


def _client(session):
    c = ProdClient()
    c.session = session
    return c


# --- credentials -----------------------------------------------------------
def test_credentials_from_env(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u")
    monkeypatch.setenv("PROD_PASSWORD", "p")
    assert client_mod._credentials() == ("u", "p")


def test_credentials_from_env_mirror_file(monkeypatch, tmp_path):
    monkeypatch.delenv("PROD_USERNAME", raising=False)
    monkeypatch.delenv("PROD_PASSWORD", raising=False)
    (tmp_path / ".env.mirror").write_text("PROD_USERNAME=fileuser\nPROD_PASSWORD=filepass\n")
    monkeypatch.setattr(client_mod, "_BASE_DIR", str(tmp_path))
    assert client_mod._credentials() == ("fileuser", "filepass")


# --- auth ------------------------------------------------------------------
def test_authenticate_success_and_token_caches(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u")
    monkeypatch.setenv("PROD_PASSWORD", "p")
    sess = FakeSession(token_status=200)
    c = _client(sess)
    assert c.token() == "TKN"
    c.token()                          # cached -> no second POST
    assert len(sess.posts) == 1


def test_authenticate_missing_credentials(monkeypatch):
    monkeypatch.delenv("PROD_USERNAME", raising=False)
    monkeypatch.delenv("PROD_PASSWORD", raising=False)
    monkeypatch.setattr(client_mod, "_BASE_DIR", "/nonexistent")
    with pytest.raises(ProdClientError, match="Missing"):
        _client(FakeSession())._authenticate()


def test_authenticate_bad_status(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u")
    monkeypatch.setenv("PROD_PASSWORD", "p")
    with pytest.raises(ProdClientError, match="Auth failed"):
        _client(FakeSession(token_status=403))._authenticate()


# --- reads -----------------------------------------------------------------
def test_get_returns_results(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u"); monkeypatch.setenv("PROD_PASSWORD", "p")
    sess = FakeSession(get_responses=[FakeResp(200, {"results": [1, 2, 3]})])
    assert _client(sess).page_by_time("2026-06-22T00:00:00Z", 50, 0) == [1, 2, 3]
    # date_from is forwarded as a param
    assert sess.gets[0][1]["dateFrom"] == "2026-06-22T00:00:00Z"


def test_get_reauths_on_401(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u"); monkeypatch.setenv("PROD_PASSWORD", "p")
    sess = FakeSession(get_responses=[FakeResp(401), FakeResp(200, {"results": ["ok"]})])
    assert _client(sess).page_student("s1", 10, 0) == ["ok"]
    assert len(sess.posts) >= 1          # re-authenticated


def test_get_raises_on_other_error(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u"); monkeypatch.setenv("PROD_PASSWORD", "p")
    sess = FakeSession(get_responses=[FakeResp(500, text="boom")])
    with pytest.raises(ProdClientError, match="500"):
        _client(sess).page_by_id(0, 10)


def test_page_by_time_without_date_from(monkeypatch):
    monkeypatch.setenv("PROD_USERNAME", "u"); monkeypatch.setenv("PROD_PASSWORD", "p")
    sess = FakeSession(get_responses=[FakeResp(200, {"results": []})])
    _client(sess).page_by_time(None, 50, 0)
    assert "dateFrom" not in sess.gets[0][1]
