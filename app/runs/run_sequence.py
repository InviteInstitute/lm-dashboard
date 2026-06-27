"""Build a chronological per-run edit-distance sequence from a student's events.

Only runProject events take part; each run after the first gets the integer APTED
edit_distance against the previous run. The first run has no predecessor (None).

Public API:
    compute_run_edit_distances(events) -> {
        "runs": [{"index": int, "edit_distance": int|None, "ts": float|None}, ...]
    }

`events` is a chronological list of dicts, each carrying at least
    {"event_type": "...", "content": {...parsed VEX log content...}, "ts": float|None}
"""
import json

from .ast_builder import xml_to_block_ast, extract_workspace_xml
from .apted_similarity import cached_edit_distance


def _extract_runs(events):
    """For each runProject event, in order, pull out the workspace XML, parse it
    into a block AST, and pair both with the event timestamp."""
    runs = []
    for ev in events:
        if ev.get("event_type") != "runProject":
            continue
        content = ev.get("content") or {}
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = {}
        xml = extract_workspace_xml(content)
        runs.append((xml, xml_to_block_ast(xml), ev.get("ts")))
    return runs


def compute_run_edit_distances(events):
    """Return {"runs": [{"index", "edit_distance", "ts"}]}. The first run's
    edit_distance is None (no predecessor)."""
    runs = _extract_runs(events)
    out = []
    for i, (xml, ast, ts) in enumerate(runs):
        if i == 0:
            dist = None
        else:
            prev_xml, prev_ast, _ = runs[i - 1]
            dist = cached_edit_distance(prev_xml, xml, prev_ast, ast)
        out.append({"index": i, "edit_distance": dist, "ts": ts})
    return {"runs": out}
