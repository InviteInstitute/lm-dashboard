"""Episode segmentation: CODE/RUN/RESET carving, soft-event absorption, and the
two pause detectors."""
from app.episode_engine import segment_session
from app.constants import PAUSE_THRESHOLD_S, SHORT_PAUSE_MIN_S


def _e(et, ts):
    return {"event_type": et, "ts": ts}


def test_empty_session():
    eps, pauses = segment_session([])
    assert eps == [] and pauses == []


def test_consecutive_code_events_merge_into_one_episode():
    events = [_e("blockMoved", 1), _e("blockChanged", 2), _e("blockCreated", 3)]
    eps, _ = segment_session(events)
    assert len(eps) == 1
    assert eps[0]["episode_type"] == "CODE" and eps[0]["event_count"] == 3


def test_run_closes_on_project_end_inclusive():
    events = [_e("runProject", 1), _e("projectEnd", 2), _e("blockMoved", 3)]
    eps, _ = segment_session(events)
    assert eps[0]["episode_type"] == "RUN"
    assert eps[0]["end_idx"] == 2                 # includes projectEnd, excludes the blockMoved
    assert eps[1]["episode_type"] == "CODE"


def test_reset_is_single_event_episode():
    events = [_e("loadProject", 1), _e("blockMoved", 2)]
    eps, _ = segment_session(events)
    assert eps[0]["episode_type"] == "RESET" and eps[0]["event_count"] == 1


def test_soft_event_absorbed_into_surrounding_code_episode():
    events = [_e("blockMoved", 1), _e("menuOpen", 2), _e("blockChanged", 3)]
    eps, _ = segment_session(events)
    assert len(eps) == 1
    assert 1 in eps[0]["soft_indices"]            # the menuOpen index
    assert eps[0]["event_count"] == 3


def test_long_gap_creates_inactive_pause_and_splits_episodes():
    gap = PAUSE_THRESHOLD_S + 10
    events = [_e("blockMoved", 0), _e("blockMoved", gap)]
    eps, pauses = segment_session(events)
    assert any(p["episode_type"] == "INACTIVE_PAUSE" for p in pauses)
    assert len(eps) == 2                          # the pause is a hard boundary


def test_no_post_run_pause_when_run_is_the_last_thing():
    # projectEnd is the final event, so there's no "next" event to measure a gap to
    events = [_e("runProject", 0), _e("projectEnd", 1)]
    _, pauses = segment_session(events)
    assert all(p["episode_type"] != "POST_RUN_PAUSE" for p in pauses)


def test_no_post_run_pause_when_run_did_not_close_cleanly():
    # RUN closed on an actionful event, not projectEnd -> no post-run pause
    events = [_e("runProject", 0), _e("blockMoved", 1), _e("blockMoved", 2)]
    _, pauses = segment_session(events)
    assert all(p["episode_type"] != "POST_RUN_PAUSE" for p in pauses)


def test_post_run_pause_detected_after_clean_run():
    gap = SHORT_PAUSE_MIN_S + 30                  # between short and threshold
    events = [_e("runProject", 0), _e("projectEnd", 1), _e("blockMoved", 1 + gap)]
    _, pauses = segment_session(events)
    assert any(p["episode_type"] == "POST_RUN_PAUSE" for p in pauses)


def test_orphan_soft_and_unknown_events_are_skipped():
    eps, _ = segment_session([_e("menuOpen", 1), _e("somethingWeird", 2)])
    assert eps == []                              # soft-before-episode + unknown: nothing opens


def test_run_absorbs_soft_then_closes_on_actionful_event():
    events = [_e("runProject", 1), _e("menuOpen", 2), _e("blockMoved", 3)]
    eps, _ = segment_session(events)
    assert eps[0]["episode_type"] == "RUN" and 1 in eps[0]["soft_indices"]   # menuOpen at idx 1
    assert eps[1]["episode_type"] == "CODE"


def test_events_without_timestamps_still_segment():
    eps, pauses = segment_session([{"event_type": "blockMoved", "ts": None},
                                   {"event_type": "blockMoved", "ts": None}])
    assert len(eps) == 1 and pauses == []         # no ts -> no pause detection, still one episode


def test_pauses_sorted_by_after_idx():
    events = [_e("blockMoved", 0), _e("blockMoved", PAUSE_THRESHOLD_S + 5),
              _e("blockMoved", 2 * PAUSE_THRESHOLD_S + 10)]
    _, pauses = segment_session(events)
    assert pauses == sorted(pauses, key=lambda p: p["after_idx"])
