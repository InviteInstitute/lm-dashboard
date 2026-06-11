"""
Strategy HMM pipeline: events -> change scores -> input buckets -> HMM states.

Public API:
    compute_strategy_states(events) -> {
        "runs": [{"index": int, "change_score": float|None,
                  "obs_bucket": int|None, "hmm_state": int|None}, ...],
        "obs_labels": {0: "...", 1: "...", 2: "..."},
    }

`events` is a list of dicts in chronological order, each with at least:
    {"event_type": "...", "content": {...parsed VEX log content...}}
Only events with event_type == "runProject" are considered.
"""
import json
import numpy as np
import joblib

from .ast_builder import xml_to_block_ast, extract_workspace_xml
from .apted_similarity import cached_change_score
from .constants import MODEL_PATH, REWRITE_THRESHOLD, OBS_LABELS


_model = None


def _get_model():
    global _model
    if _model is None:
        _model = joblib.load(MODEL_PATH)
    return _model


def bucket_change_score(score):
    """Map a change_score to one of the 3 input categories. None passes through."""
    if score is None:
        return None
    if score == 0:
        return 0
    if score < REWRITE_THRESHOLD:
        return 1
    return 2


def _extract_runs(events):
    """Pull (xml, ast) per runProject event in chronological order."""
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
        ast = xml_to_block_ast(xml)
        runs.append((xml, ast))
    return runs


def compute_strategy_states(events):
    """Run the full pipeline on a chronological event list."""
    runs = _extract_runs(events)
    runs_out = []
    obs_seq = []

    for i, (xml, ast) in enumerate(runs):
        if i == 0:
            score = None
            bucket = None
        else:
            prev_xml, prev_ast = runs[i - 1]
            score = cached_change_score(prev_xml, xml, prev_ast, ast)
            bucket = bucket_change_score(score)
            obs_seq.append(bucket)
        runs_out.append({"index": i, "change_score": score, "obs_bucket": bucket, "hmm_state": None})

    if len(obs_seq) >= 1:
        model = _get_model()
        X = np.array(obs_seq, dtype=int).reshape(-1, 1)
        states = model.predict(X)
        for k, state in enumerate(states):
            # obs_seq[k] corresponds to runs_out[k + 1] (first run has no bucket)
            runs_out[k + 1]["hmm_state"] = int(state)

    return {"runs": runs_out, "obs_labels": OBS_LABELS}
