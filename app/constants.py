"""
Central constants for the dashboard backend -- one home for every tunable.

Covers the trigger thresholds and labels, the episode segmentation taxonomy +
thresholds, the APTED edit costs, limits, and the pipeline's cursor name. db.py
keeps its own private implementation constants (the SQL schema, datetime formats,
serialization field lists), and env-derived configuration lives in config.py.
"""

# ==========================================================================
# Triggers
# ==========================================================================
TRIGGER_LABELS = {
    "wheel_spin": "Wheel-spinning", "resilience": "Resilience", "inactive": "Inactive",
    "explorer": "Explorer", "iterative": "Step-by-Step",
}
RE_ALERT_SECONDS = 600                # re-open an acked sustained trigger still holding after 10 min
TRIGGER_RECENT_SECONDS = 120          # a resolved (or momentary) trigger lingers in the feed this long (2 min)

# --- Edit-distance trigger thresholds (see docs/superpowers/specs/NoHMM.md) ---
WHEEL_SPIN_ZERO_RUNS = 6        # >= this many consecutive zero-edit runs -> wheel_spin
RESILIENCE_ZERO_RUNS = 4        # an edit after >= this many zeros -> resilience
INACTIVE_TRIGGER_SECONDS = 240  # idle > this many seconds -> inactive (separate from the segmenter's 300s)
EXPLORER_EDIT_DISTANCE = 13     # a single run with edit_distance >= this -> explorer
ITERATIVE_EDIT_MIN = 1          # runs with edit_distance > this count toward iterative
ITERATIVE_DEFAULT_THRESHOLD = 6 # count of such runs that fires iterative

# Reference only -- not used until the playground name is in telemetry.
ITERATIVE_THRESHOLDS = {"CoralReefCleanup": 5, "CastleCrasherPlus": 6, "RoverRescue": 3}

# Headline-status precedence; only wheel_spin > resilience is load-bearing.
TRIGGER_PRIORITY = ("wheel_spin", "inactive", "resilience", "explorer", "iterative")

# ==========================================================================
# Limits / timing
# ==========================================================================
MAX_STUDENT_IDS = 500                 # cap on ?students= ids per request (under SQLite's variable limit)
BUFFER_MAX = 5000                     # per-student in-memory rolling event history
PAUSED_POLL_S = 1.0                   # how often the paused daemon re-checks the resume flag
VIEWER_PRESENT_SECONDS = 90           # dead-man's switch: prod polling pauses if no dashboard poll within this window

# ==========================================================================
# Pipeline
# ==========================================================================
CURSOR_NAME = "vex_poll"              # the ingest cursor's row name in the DB

# ==========================================================================
# Episode segmentation
# Mirrors the semantics in learner-model-pipeline/src/episodes.py. Hard-boundary
# episode types stop surrounding episodes from merging regardless of the time
# gap; soft events never form an episode of their own and fold into whatever
# episode surrounds them.
# ==========================================================================
PAUSE_THRESHOLD_S = 300.0             # gap >= this becomes INACTIVE_PAUSE
SHORT_PAUSE_MIN_S = 5.0               # smallest gap that counts as a contextual pause
PAUSE_MAX_S = 86400.0                 # ignore gaps > 24h (likely a session boundary)
CODE_MERGE_GAP_S = None               # None -> use PAUSE_THRESHOLD_S (currently unused)
RESET_MERGE_GAP_S = None              # None -> use PAUSE_THRESHOLD_S (currently unused)

# Event types that open an episode, by kind.
CODE_EVENTS = frozenset({"blockMoved", "blockChanged", "blockCreated", "blockDeleted"})
RUN_START_EVENTS = frozenset({"runProject"})
RUN_END_EVENTS = frozenset({"projectEnd"})
RESET_EVENTS = frozenset({"loadProject", "newProject"})

# Episode types that act as merge barriers regardless of the merge gaps.
HARD_BOUNDARY_EPISODE_TYPES = frozenset({"RUN", "CODE", "RESET", "INACTIVE_PAUSE", "POST_RUN_PAUSE"})
# Pause categories tagged as "hard" boundaries downstream.
HARD_PAUSE_TYPES = frozenset({"INACTIVE_PAUSE", "POST_RUN_PAUSE"})

# Event types absorbed into surrounding episodes (no episode of their own).
SOFT_EVENT_TYPES = frozenset({
    "menuOpen", "menuSelect", "menuClose",                                    # nav_ui
    "playgroundOpen", "playgroundClosed", "playgroundHidden",                 # playground_ui
    "playgroundShow", "playgroundReset",
    "playgroundData",                                                         # performance_data
})

# Subset of SOFT_EVENT_TYPES skipped when scanning for the "next actionful event
# after a RUN" during POST_RUN_PAUSE detection. Caitlin's rule (episodes.py:
# 763-766) excludes nav_ui -- menu events count as actionful there.
POST_RUN_PAUSE_TRANSPARENT_TYPES = frozenset({
    "playgroundOpen", "playgroundClosed", "playgroundHidden",                 # playground_ui
    "playgroundShow", "playgroundReset",
    "playgroundData",                                                         # performance_data
})


def boundary_kind(episode_type):
    """Classify an episode_type as a 'hard' or 'soft' boundary (only the pause
    types count as hard here)."""
    return "hard" if episode_type.upper() in HARD_PAUSE_TYPES else "soft"


def effective_code_merge_gap_s():
    return CODE_MERGE_GAP_S if CODE_MERGE_GAP_S is not None else PAUSE_THRESHOLD_S


def effective_reset_merge_gap_s():
    return RESET_MERGE_GAP_S if RESET_MERGE_GAP_S is not None else PAUSE_THRESHOLD_S

# ==========================================================================
# APTED edit costs (Hyeongjo's colab). Edge nodes (the synthetic connectors our
# AST inserts between parent and child) cost 0 to add/remove, so adding one real
# block scores 1 not 2; everything else is 1.0, so edit_distance is a whole number.
# ==========================================================================
BLOCK_DELETE_COST = 1.0
BLOCK_INSERT_COST = 1.0
EDGE_DELETE_COST = 0.0
EDGE_INSERT_COST = 0.0
FIELD_CHANGE_COST = 1.0
TYPE_CHANGE_COST = 1.0
EDGE_CHANGE_COST = 1.0
