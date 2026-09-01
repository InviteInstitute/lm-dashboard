"""
Central constants for the dashboard backend -- one home for every tunable.

The trigger thresholds, the episode segmentation taxonomy, the trigger labels, and
the APTED edit costs are the shared engine's contract, so they are imported from
learner_models.constants (the agent-lm-packages submodule) and re-exported here.
That keeps a single source of truth: the dashboard's numbers cannot drift from the
engine that actually computes on them. The dashboard-only knobs (feed timings,
buffer sizes, the cursor name, the unused merge-gap overrides) stay defined here.

db.py keeps its own private implementation constants (the SQL schema, datetime
formats, serialization field lists), and env-derived configuration lives in config.py.
"""

# Shared engine contract, re-exported from the submodule so it is the one source
# of truth for both the dashboard and the trigger/episode engine.
from learner_models.constants import (
    BLOCK_DELETE_COST,
    BLOCK_INSERT_COST,
    CODE_EVENTS,
    EDGE_CHANGE_COST,
    EDGE_DELETE_COST,
    EDGE_INSERT_COST,
    EXPLORER_EDIT_DISTANCE,
    FIELD_CHANGE_COST,
    HARD_BOUNDARY_EPISODE_TYPES,
    HARD_PAUSE_TYPES,
    INACTIVE_TRIGGER_SECONDS,
    ITERATIVE_DEFAULT_THRESHOLD,
    ITERATIVE_EDIT_MIN,
    ITERATIVE_THRESHOLDS,
    PAUSE_MAX_S,
    PAUSE_THRESHOLD_S,
    POST_RUN_PAUSE_TRANSPARENT_TYPES,
    RE_ALERT_SECONDS,
    RESET_EVENTS,
    RESILIENCE_ZERO_RUNS,
    RUN_END_EVENTS,
    RUN_START_EVENTS,
    SHORT_PAUSE_MIN_S,
    SOFT_EVENT_TYPES,
    TRIGGER_LABELS,
    TYPE_CHANGE_COST,
    WHEEL_SPIN_ZERO_RUNS,
    boundary_kind,
)

# ==========================================================================
# Dashboard-only trigger + feed knobs (not part of the shared engine contract)
# ==========================================================================
TRIGGER_RECENT_SECONDS = (
    420  # a resolved (or momentary) trigger lingers in the feed this long (7 min)
)
TRIGGER_TOUCH_THROTTLE_S = (
    30  # min seconds between last_seen_at refreshes on a held sustained trigger;
)
# the idle-time display is minute-granular, so refreshing every tick is waste

# Headline-status precedence; only wheel_spin > resilience is load-bearing.
TRIGGER_PRIORITY = ("wheel_spin", "inactive", "resilience", "explorer", "iterative")

# ==========================================================================
# Limits / timing
# ==========================================================================
MAX_STUDENT_IDS = 500  # cap on ?students= ids per request (under SQLite's variable limit)
BUFFER_MAX = 5000  # per-student in-memory rolling event history
PAUSED_POLL_S = 1.0  # how often the paused daemon re-checks the resume flag
VIEWER_PRESENT_SECONDS = (
    90  # dead-man's switch: prod polling pauses if no dashboard poll within this window
)

# ==========================================================================
# Pipeline
# ==========================================================================
CURSOR_NAME = "vex_poll"  # the ingest cursor's row name in the DB

# ==========================================================================
# Episode segmentation -- dashboard-only overrides on top of the shared taxonomy.
# ==========================================================================
CODE_MERGE_GAP_S = None  # None -> use PAUSE_THRESHOLD_S (currently unused)
RESET_MERGE_GAP_S = None  # None -> use PAUSE_THRESHOLD_S (currently unused)


def effective_code_merge_gap_s():
    return CODE_MERGE_GAP_S if CODE_MERGE_GAP_S is not None else PAUSE_THRESHOLD_S


def effective_reset_merge_gap_s():
    return RESET_MERGE_GAP_S if RESET_MERGE_GAP_S is not None else PAUSE_THRESHOLD_S


# Re-exported shared names plus the dashboard-only ones, so `from app.constants
# import X` keeps working for every X it used to expose.
__all__ = [
    # shared engine contract (from learner_models.constants)
    "TRIGGER_LABELS",
    "RE_ALERT_SECONDS",
    "WHEEL_SPIN_ZERO_RUNS",
    "RESILIENCE_ZERO_RUNS",
    "INACTIVE_TRIGGER_SECONDS",
    "EXPLORER_EDIT_DISTANCE",
    "ITERATIVE_EDIT_MIN",
    "ITERATIVE_DEFAULT_THRESHOLD",
    "ITERATIVE_THRESHOLDS",
    "PAUSE_THRESHOLD_S",
    "SHORT_PAUSE_MIN_S",
    "PAUSE_MAX_S",
    "CODE_EVENTS",
    "RUN_START_EVENTS",
    "RUN_END_EVENTS",
    "RESET_EVENTS",
    "HARD_BOUNDARY_EPISODE_TYPES",
    "HARD_PAUSE_TYPES",
    "SOFT_EVENT_TYPES",
    "POST_RUN_PAUSE_TRANSPARENT_TYPES",
    "boundary_kind",
    "BLOCK_DELETE_COST",
    "BLOCK_INSERT_COST",
    "EDGE_DELETE_COST",
    "EDGE_INSERT_COST",
    "FIELD_CHANGE_COST",
    "TYPE_CHANGE_COST",
    "EDGE_CHANGE_COST",
    # dashboard-only
    "TRIGGER_RECENT_SECONDS",
    "TRIGGER_TOUCH_THROTTLE_S",
    "TRIGGER_PRIORITY",
    "MAX_STUDENT_IDS",
    "BUFFER_MAX",
    "PAUSED_POLL_S",
    "VIEWER_PRESENT_SECONDS",
    "CURSOR_NAME",
    "CODE_MERGE_GAP_S",
    "RESET_MERGE_GAP_S",
    "effective_code_merge_gap_s",
    "effective_reset_merge_gap_s",
]
