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


def test_inactive_pause_cuts_a_run_short():
    # Pass 1 finds a long idle gap and marks it a hard boundary; pass 2's RUN
    # extension must honor that boundary and stop, instead of swallowing the event
    # on the far side of the pause into the same RUN episode. The pause sits between
    # idx 0 and idx 1 (after_idx=0), so the RUN's extension loop hits the boundary
    # on its very first step and the RUN stays a single event.
    events = [_e("runProject", 0), _e("blockMoved", PAUSE_THRESHOLD_S + 10)]
    eps, pauses = segment_session(events)
    assert any(p["episode_type"] == "INACTIVE_PAUSE" for p in pauses)
    assert eps[0]["episode_type"] == "RUN" and eps[0]["event_count"] == 1
    assert eps[1]["episode_type"] == "CODE"      # post-pause event opens its own episode


def test_code_episode_closes_on_run_start():
    # A CODE run hits an actionful, non-code, non-soft event (runProject) and must
    # close there rather than swallowing it.
    events = [_e("blockMoved", 1), _e("runProject", 2)]
    eps, _ = segment_session(events)
    assert eps[0]["episode_type"] == "CODE" and eps[0]["event_count"] == 1
    assert eps[1]["episode_type"] == "RUN"


def test_post_run_pause_skips_transparent_events():
    # playgroundData is "transparent": the post-run gap is measured past it to the
    # next real event, so a pause is still detected even with UI noise in between.
    gap = SHORT_PAUSE_MIN_S + 30
    events = [_e("runProject", 0), _e("projectEnd", 1),
              _e("playgroundData", 1.1), _e("blockMoved", 1 + gap)]
    _, pauses = segment_session(events)
    assert any(p["episode_type"] == "POST_RUN_PAUSE" for p in pauses)


def test_post_run_pause_needs_timestamps_on_both_ends():
    # The event after a clean RUN has no ts, so the gap can't be measured: no pause.
    events = [_e("runProject", 0), _e("projectEnd", 1), _e("blockMoved", None)]
    _, pauses = segment_session(events)
    assert all(p["episode_type"] != "POST_RUN_PAUSE" for p in pauses)
