"""
Shared configuration for the episode engine: the pause thresholds and the
hard/soft boundary taxonomy the segmenter reads.

These mirror the segmentation semantics in learner-model-pipeline/src/episodes.py.
Hard-boundary episode types stop surrounding episodes from merging no matter the
time gap; soft events never form an episode of their own and are folded into
whatever episode surrounds them.
"""

# Pause / merge thresholds (seconds)
PAUSE_THRESHOLD_S: float = 300.0       # gap >= this becomes INACTIVE_PAUSE
SHORT_PAUSE_MIN_S: float = 5.0         # smallest gap that counts as a contextual pause
PAUSE_MAX_S: float = 86400.0           # ignore gaps > 24h (likely session boundary)
CODE_MERGE_GAP_S: float | None = None  # None -> use PAUSE_THRESHOLD_S
RESET_MERGE_GAP_S: float | None = None # None -> use PAUSE_THRESHOLD_S


# Episode types that act as merge barriers. CODE/RESET episodes cannot merge
# across these regardless of code_merge_gap_s / reset_merge_gap_s.
HARD_BOUNDARY_EPISODE_TYPES: frozenset[str] = frozenset({
    "RUN",
    "CODE",
    "RESET",
    "INACTIVE_PAUSE",
    "POST_RUN_PAUSE",
})

# Pause categories tagged as "hard" boundaries downstream.
HARD_PAUSE_TYPES: frozenset[str] = frozenset({
    "INACTIVE_PAUSE",
    "POST_RUN_PAUSE",
})

# Event types absorbed into surrounding episodes (no episode of their own).
SOFT_EVENT_TYPES: frozenset[str] = frozenset({
    # nav_ui
    "menuOpen", "menuSelect", "menuClose",
    # playground_ui
    "playgroundOpen", "playgroundClosed", "playgroundHidden",
    "playgroundShow", "playgroundReset",
    # performance_data
    "playgroundData",
})

# Subset of SOFT_EVENT_TYPES skipped when scanning for the "next actionful
# event after a RUN" during POST_RUN_PAUSE detection. Caitlin's rule
# (episodes.py:763-766) excludes `nav_ui` from this skip set - menu events
# count as actionful for that purpose. Matching that strictly here.
POST_RUN_PAUSE_TRANSPARENT_TYPES: frozenset[str] = frozenset({
    # playground_ui
    "playgroundOpen", "playgroundClosed", "playgroundHidden",
    "playgroundShow", "playgroundReset",
    # performance_data
    "playgroundData",
})


def boundary_kind(episode_type: str) -> str:
    """Classify an episode_type as a 'hard' or 'soft' boundary (only the pause
    types count as hard here)."""
    return "hard" if episode_type.upper() in HARD_PAUSE_TYPES else "soft"


def effective_code_merge_gap_s() -> float:
    return CODE_MERGE_GAP_S if CODE_MERGE_GAP_S is not None else PAUSE_THRESHOLD_S


def effective_reset_merge_gap_s() -> float:
    return RESET_MERGE_GAP_S if RESET_MERGE_GAP_S is not None else PAUSE_THRESHOLD_S
