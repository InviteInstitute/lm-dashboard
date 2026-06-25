"""
Batch episode segmentation: carving a session into CODE / RUN / RESET episodes.

It walks a time-sorted event sequence and groups it into episodes, stopping at
hard-pause boundaries and pulling "soft" UI events into whatever episode
surrounds them. The rules mirror the segmentation logic in Caitlin's repo.

segment_episodes inputs:
- events: dicts with at least {'event_type', 'ts'}, sorted by ts.
- hard_pause_after_idx: a set of indices i where a hard pause sits between
  events[i] and events[i+1]. Computed by the pause detectors below from gaps
  >= PAUSE_THRESHOLD_S (INACTIVE_PAUSE) or from POST_RUN_PAUSE.

segment_episodes output:
- a list of episode dicts: {episode_type, boundary, start_idx, end_idx,
  start_ts, end_ts, event_count, soft_indices}, where start_idx is inclusive and
  end_idx is exclusive (Caitlin's repo convention).
"""
from app.constants import (
    boundary_kind,
    SOFT_EVENT_TYPES,
    PAUSE_THRESHOLD_S,
    SHORT_PAUSE_MIN_S,
    PAUSE_MAX_S,
    POST_RUN_PAUSE_TRANSPARENT_TYPES,
    CODE_EVENTS,
    RUN_START_EVENTS,
    RUN_END_EVENTS,
    RESET_EVENTS,
)


def _classify_event(event_type: str) -> str:
    """Map an event type to the episode kind it would open (CODE, RUN, or RESET),
    or '' if it opens nothing on its own."""
    if event_type in CODE_EVENTS:
        return 'CODE'
    if event_type in RUN_START_EVENTS:
        return 'RUN'
    if event_type in RESET_EVENTS:
        return 'RESET'
    return ''


def segment_episodes(events: list[dict], hard_pause_after_idx: set[int]) -> list[dict]:
    """Pass 2: scan the events once and emit episodes. RESET is a single event;
    RUN runs until projectEnd (inclusive), another actionful event, or a hard
    pause; CODE runs through consecutive code events. Soft events are absorbed
    into the open episode, and orphan soft/unknown events are skipped."""
    episodes: list[dict] = []
    i = 0
    n = len(events)

    while i < n:
        et = events[i].get('event_type', '')

        if et in SOFT_EVENT_TYPES:
            # Orphan soft event before any episode opens - skip it
            # (absorption only happens inside an episode below).
            i += 1
            continue

        kind = _classify_event(et)
        if not kind:
            # Unknown event type - skip
            i += 1
            continue

        start = i
        soft_indices: list[int] = []
        j = i

        if kind == 'RESET':
            # Single-event episode. RESET is structural - one event, one episode.
            j = i + 1

        elif kind == 'RUN':
            # Extend through soft events; close at projectEnd (inclusive) or
            # at the first non-soft event that isn't a continuation, or at a hard pause.
            j = i + 1
            while j < n:
                if (j - 1) in hard_pause_after_idx:
                    break
                t = events[j].get('event_type', '')
                if t in RUN_END_EVENTS:
                    j += 1  # include the projectEnd event in the RUN episode
                    break
                if t in SOFT_EVENT_TYPES:
                    soft_indices.append(j)
                    j += 1
                    continue
                # Any other actionful event closes the RUN
                break

        elif kind == 'CODE':
            # Extend through more CODE events, absorbing soft events.
            # Stop on hard pause, RUN start, RESET event, or other actionful event.
            j = i + 1
            while j < n:
                if (j - 1) in hard_pause_after_idx:
                    break
                t = events[j].get('event_type', '')
                if t in CODE_EVENTS:
                    j += 1
                    continue
                if t in SOFT_EVENT_TYPES:
                    soft_indices.append(j)
                    j += 1
                    continue
                break

        episodes.append({
            'episode_type': kind,
            'boundary': boundary_kind(kind),  # all of CODE/RUN/RESET are hard
            'start_idx': start,
            'end_idx': j,
            'start_ts': events[start].get('ts'),
            'end_ts': events[j - 1].get('ts') if j - 1 < n else None,
            'event_count': j - start,
            'soft_indices': soft_indices,
        })
        i = j

    return episodes


def _detect_inactive_pauses(events: list[dict]) -> list[dict]:
    """Pass 1: turn long idle gaps into INACTIVE_PAUSE hard boundaries. A gap of
    at least PAUSE_THRESHOLD_S qualifies; gaps that are trivially short or absurdly
    long (> PAUSE_MAX_S, i.e. across sessions) are ignored."""
    pauses = []
    for i in range(1, len(events)):
        prev_ts = events[i - 1].get('ts')
        curr_ts = events[i].get('ts')
        if prev_ts is None or curr_ts is None:
            continue
        gap = curr_ts - prev_ts
        if gap <= SHORT_PAUSE_MIN_S or gap > PAUSE_MAX_S:
            continue
        if gap >= PAUSE_THRESHOLD_S:
            pauses.append({
                'after_idx': i - 1,
                'duration': gap,
                'episode_type': 'INACTIVE_PAUSE',
                'boundary': 'hard',
            })
    return pauses


def _detect_post_run_pauses(events: list[dict], episodes: list[dict]) -> list[dict]:
    """Pass 3: detect the "watched it run, then paused" gap. For each RUN that
    closed cleanly with projectEnd, skip past any transparent UI events and, if
    the next real event lands within (SHORT_PAUSE_MIN_S, PAUSE_THRESHOLD_S), mark
    a POST_RUN_PAUSE. Mirrors Caitlin's _identify_post_run_pauses."""
    pauses = []
    for ep in episodes:
        if ep['episode_type'] != 'RUN':
            continue
        last_idx = ep['end_idx'] - 1
        if last_idx < 0 or last_idx >= len(events):
            continue
        if events[last_idx].get('event_type') != 'projectEnd':
            continue  # RUN didn't close cleanly
        j = ep['end_idx']
        while j < len(events) and events[j].get('event_type', '') in POST_RUN_PAUSE_TRANSPARENT_TYPES:
            j += 1
        if j >= len(events):
            continue
        end_ts = events[j].get('ts')
        start_ts = events[last_idx].get('ts')
        if end_ts is None or start_ts is None:
            continue
        gap = end_ts - start_ts
        if gap <= SHORT_PAUSE_MIN_S or gap >= PAUSE_THRESHOLD_S:
            continue
        pauses.append({
            'after_idx': last_idx,
            'duration': gap,
            'episode_type': 'POST_RUN_PAUSE',
            'boundary': 'hard',
        })
    return pauses


def segment_session(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """The public entry point: run all three passes in the order Caitlin's repo
    uses.

    1. Find INACTIVE_PAUSE gaps (>= PAUSE_THRESHOLD_S) and treat them as hard
       boundaries.
    2. Segment CODE/RUN/RESET episodes honoring those boundaries, absorbing soft
       events into the surrounding episode.
    3. Derive POST_RUN_PAUSE for RUN episodes that ended on projectEnd and have a
       qualifying gap (> SHORT_PAUSE_MIN_S, < PAUSE_THRESHOLD_S) before the next
       non-transparent event.

    Each event needs an 'event_type' (str) and a 'ts' (float seconds, or None,
    an event with no ts still segments but can't anchor a pause).

    Returns (episodes, pauses), with pauses sorted by after_idx so the timeline
    renderer can look them up by position.
    """
    inactive = _detect_inactive_pauses(events)
    hard_after = {p['after_idx'] for p in inactive}
    episodes = segment_episodes(events, hard_after)
    post_run = _detect_post_run_pauses(events, episodes)
    pauses = sorted(inactive + post_run, key=lambda p: p['after_idx'])
    return episodes, pauses
