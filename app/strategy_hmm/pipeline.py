"""
The strategy HMM pipeline, end to end: it turns a student's event stream into a
per-run sequence of latent strategy states. The chain is

    runs -> change scores (vs the previous run) -> input buckets -> HMM states.

Public API:
    compute_strategy_states(events) -> {
        "runs": [{"index": int, "change_score": float|None,
                  "obs_bucket": int|None, "hmm_state": int|None}, ...],
        "obs_labels": {0: "...", 1: "...", 2: "..."},
    }

`events` is a chronologically-ordered list of dicts, each carrying at least
    {"event_type": "...", "content": {...parsed VEX log content...}}
and only the runProject events take part; everything else is ignored.
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
    """Quantize a change_score into one of three HMM input categories: 0 for an
    identical run, 1 for a sub-threshold edit, 2 for a rewrite. None stays None."""
    if score is None:
        return None
    if score == 0:
        return 0
    if score < REWRITE_THRESHOLD:
        return 1
    return 2


def _extract_runs(events):
    """For each runProject event, in order, pull out the workspace XML, parse it
    into a block AST, and pair both with the event timestamp. Returns a list of
    (xml, ast, ts) tuples."""
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
        runs.append((xml, ast, ev.get("ts")))
    return runs


def compute_strategy_states(events):
    """Run the whole pipeline over a chronological event list and return the
    per-run records plus the observation labels. Each run after the first gets a
    change_score against its predecessor, a bucket, and an HMM-decoded state; the
    first run has no predecessor, so its score, bucket, and state stay None."""
    runs = _extract_runs(events)
    runs_out = []
    obs_seq = []

    for i, (xml, ast, ts) in enumerate(runs):
        if i == 0:
            score = None
            bucket = None
        else:
            prev_xml, prev_ast, _ = runs[i - 1]
            score = cached_change_score(prev_xml, xml, prev_ast, ast)
            bucket = bucket_change_score(score)
            obs_seq.append(bucket)
        runs_out.append({"index": i, "change_score": score, "obs_bucket": bucket,
                         "hmm_state": None, "ts": ts})

    if len(obs_seq) >= 1:
        model = _get_model()
        X = np.array(obs_seq, dtype=int).reshape(-1, 1)
        states = model.predict(X)
        for k, state in enumerate(states):
            # obs_seq[k] corresponds to runs_out[k + 1] (first run has no bucket)
            runs_out[k + 1]["hmm_state"] = int(state)

    return {"runs": runs_out, "obs_labels": OBS_LABELS}
