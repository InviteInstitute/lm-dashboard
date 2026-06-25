"""
Central constants for the dashboard backend -- one home for every tunable.

Covers the app-level knobs (states, trigger thresholds, limits), the episode
segmentation taxonomy + thresholds, the strategy-HMM tuning values, and the
pipeline's cursor name. db.py keeps its own private implementation constants
(the SQL schema, datetime formats, serialization field lists), and env-derived
configuration lives in config.py.
"""
import os

# ==========================================================================
# Strategy (HMM) states
# ==========================================================================
STUCK_STATE = 2                       # the "stuck" / wheel-spinning HMM state
STATE_LABELS = {0: "iterator", 1: "explorer", 2: "stuck"}

# ==========================================================================
# Triggers
# ==========================================================================
TRIGGER_LABELS = {"wheel_spin": "Wheel-spinning", "inactive": "Inactive", "big_change": "Big rewrite"}
SUSTAINED_TRIGGERS = ("wheel_spin", "inactive")   # the rest (big_change) fire-and-resolve at once
INACTIVE_SECONDS = 300                # 5 min idle -> "inactive"; matches the segmenter's INACTIVE_PAUSE
BIG_CHANGE_SCORE = 0.5                # APTED change_score at/above this fires "big rewrite"
RE_ALERT_SECONDS = 600                # re-open an acked sustained trigger still holding after 10 min
TRIGGER_RECENT_SECONDS = 120          # a resolved trigger lingers in the feed this long (2 min)

# ==========================================================================
# Limits / timing
# ==========================================================================
MAX_STUDENT_IDS = 500                 # cap on ?students= ids per request (under SQLite's variable limit)
BUFFER_MAX = 5000                     # per-student in-memory rolling event history
PAUSED_POLL_S = 1.0                   # how often the paused daemon re-checks the resume flag

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
# Strategy HMM tuning
# Copied verbatim from Hyeongjo's training Colab; they must stay in lockstep
# with the saved model (strategy_hmm/model.pkl) for live inference to match how
# it was trained. Treat as fixed, not knobs.
# ==========================================================================
MODEL_PATH = os.path.join(os.path.dirname(__file__), "strategy_hmm", "model.pkl")

# Cutoff between "step by step" and a full "rewrite" when bucketing change_score:
# the 95th percentile of the non-zero change scores in the training data.
REWRITE_THRESHOLD = 0.221151

# APTED edit costs, the BlocklyConfig defaults used at training time.
DELETION_COST = 1.0
INSERTION_COST = 1.0
FIELD_CHANGE_COST = 0.3
TYPE_CHANGE_COST = 1.0
EDGE_CHANGE_COST = 1.0

# Smoothing term in the similarity normalization:
#   sim = 1 - dist / (max_tree_size + SIMILARITY_SMOOTHING)
# Damps the score for very small trees, where a one-block change would otherwise
# look like a near-total rewrite.
SIMILARITY_SMOOTHING = 10

# Human-readable names for the three observation buckets fed into the HMM.
OBS_LABELS = {
    0: "relying_on_fortune",   # change_score == 0 (the code didn't change at all)
    1: "step_by_step",         # 0 < change_score < REWRITE_THRESHOLD (incremental)
    2: "rewrite",              # change_score >= REWRITE_THRESHOLD (large overhaul)
}
