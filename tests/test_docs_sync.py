"""scripts/docs_sync.py writes only what the model may write: docs pages, the README and the
nav, and never an em dash or a middle dot."""

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parent.parent / "scripts" / "docs_sync.py"
_spec = importlib.util.spec_from_file_location("docs_sync", _path)
docs_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docs_sync)


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
    assert docs_sync.apply(answer) == ["docs/guide.md", "README.md"]
    assert (tmp_path / "docs/guide.md").read_text() == "Alerts stay - ten minutes - now.\n"
    assert not (tmp_path / "app").exists()


def test_writable_respects_protected(monkeypatch):
    monkeypatch.setattr(docs_sync, "WRITABLE", ("docs/**.md", "README.md"))
    monkeypatch.setattr(docs_sync, "PROTECTED", ("docs/changes/*",))
    assert not docs_sync.writable("docs/changes/x.md")
    assert docs_sync.writable("docs/a/b.md")
    assert docs_sync.writable("README.md")
    assert not docs_sync.writable("AGENTS.md")
    assert not docs_sync.writable("docs/../app/x.md")
