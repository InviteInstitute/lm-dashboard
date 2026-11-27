"""scripts/docs_sync.py, the docs bot every INVITE repo shares, writes only what a repo's
settings let it write, and never an em dash or a middle dot."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("docs_sync", ROOT / "scripts" / "docs_sync.py")
docs_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docs_sync)


def settings(**kw):
    return docs_sync.SETTINGS | {"about": "x", "new_page_rule": "x", "code_paths": []} | kw


def test_this_repos_settings_load():
    s = docs_sync.load_settings(ROOT / ".github/docs-bot.toml")
    assert s["writable"] == ["docs/*.md", "README.md", "zensical.toml"]


def test_settings_refuse_unknown_and_missing_keys(tmp_path):
    path = tmp_path / "docs-bot.toml"
    path.write_text('about = "x"\nnew_page_rule = "x"\nwriteable = ["*"]\ncode_paths = []\n')
    with pytest.raises(SystemExit, match="unknown \\['writeable'\\], missing \\['writable'\\]"):
        docs_sync.load_settings(path)


def test_apply_writes_docs_and_ignores_everything_else(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_sync, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/same.md").write_text("unchanged\n")
    answer = (
        "Fixed two pages.\n"
        "<<<FILE docs/guide.md\nAlerts stay \u2014 ten minutes \u00b7 now.\n>>>END\n"
        "<<<FILE docs/same.md\nunchanged\n>>>END\n"
        "<<<FILE README.md\n# Title\n>>>END\n"
        "<<<FILE app/main.py\nimport os\n>>>END\n"
        "<<<FILE docs/../app/x.md\nno\n>>>END\n"
    )
    lm = settings(writable=["docs/*.md", "README.md", "zensical.toml"])
    assert docs_sync.apply(answer, lm) == ["docs/guide.md", "README.md"]
    assert (tmp_path / "docs/guide.md").read_text() == "Alerts stay - ten minutes - now.\n"
    assert not (tmp_path / "app").exists()


def test_writable_respects_protected():
    s = settings(writable=["docs/**.md", "README.md"], protected=["docs/changes/*"])
    assert not docs_sync.writable("docs/changes/x.md", s)
    assert docs_sync.writable("docs/a/b.md", s)
    assert docs_sync.writable("README.md", s)
    assert not docs_sync.writable("AGENTS.md", s)
    assert not docs_sync.writable("docs/../app/x.md", s)


def test_writable_rejects_paths_that_normalize_elsewhere():
    s = settings(writable=["docs/*.md"], protected=["docs/changes/*"])
    assert not docs_sync.writable("docs//changes/x.md", s)
    assert not docs_sync.writable("docs/./changes/x.md", s)
    assert not docs_sync.writable("/docs/a.md", s)
    assert docs_sync.writable("docs/a.md", s)


def test_ask_falls_back_to_the_next_model(monkeypatch):
    import io
    import json
    import urllib.error

    tried = []

    def fake_urlopen(req, timeout):
        model = json.loads(req.data)["model"]
        tried.append(model)
        if model == "slow":
            raise urllib.error.HTTPError(req.full_url, 500, "Upstream error", {}, io.BytesIO(b""))
        out = {"choices": [{"message": {"content": "NO_CHANGES"}, "finish_reason": "stop"}]}
        return io.BytesIO(json.dumps(out).encode())

    monkeypatch.setattr(docs_sync.urllib.request, "urlopen", fake_urlopen)
    assert docs_sync.ask("s", "u", ["slow", "fast", "never"], "key") == "NO_CHANGES"
    assert tried == ["slow", "fast"]  # one try each, and none after an answer
