"""
The backend's tunable numbers.

The trigger thresholds, the trigger labels and the APTED edit costs belong to the
shared engine (learner_models.constants, in the agent-lm-packages submodule), so
the ones the dashboard reads are re-exported from there rather than copied: the
dashboard's numbers cannot drift from the engine that computes on them. The
dashboard's own knobs (feed timing, buffer size, the cursor name) are defined here.

db.py keeps its private implementation constants (the schema, datetime formats,
export field lists), and settings from the environment live in config.py.
"""

from learner_models.constants import (
    EDGE_CHANGE_COST,
    FIELD_CHANGE_COST,
    INACTIVE_TRIGGER_SECONDS,
    ITERATIVE_EDIT_MIN,
    ITERATIVE_THRESHOLDS,
    PAUSE_THRESHOLD_S,
    RE_ALERT_SECONDS,
    SHORT_PAUSE_MIN_S,
    TRIGGER_LABELS,
    TYPE_CHANGE_COST,
)

# ---- the alert feed ----
# A resolved (or momentary) trigger stays in the feed this long (7 minutes).
TRIGGER_RECENT_SECONDS = 420
# The fewest seconds between last_seen_at refreshes on a sustained trigger that
# is still holding. The idle time shows in whole minutes, so every tick is waste.
TRIGGER_TOUCH_THROTTLE_S = 30

# ---- the daemon ----
BUFFER_MAX = 5000  # per-student in-memory rolling event history
PAUSED_POLL_S = 1.0  # how often a paused daemon checks whether to resume
# Dead-man's switch: a board's production polling pauses when no dashboard has
# polled or held the stream for this long.
VIEWER_PRESENT_SECONDS = 90
CURSOR_NAME = "vex_poll"  # the ingest cursor's row name in the database

__all__ = [
    # from the shared engine
    "EDGE_CHANGE_COST",
    "FIELD_CHANGE_COST",
    "INACTIVE_TRIGGER_SECONDS",
    "ITERATIVE_EDIT_MIN",
    "ITERATIVE_THRESHOLDS",
    "PAUSE_THRESHOLD_S",
    "RE_ALERT_SECONDS",
    "SHORT_PAUSE_MIN_S",
    "TRIGGER_LABELS",
    "TYPE_CHANGE_COST",
    # the dashboard's own
    "BUFFER_MAX",
    "CURSOR_NAME",
    "PAUSED_POLL_S",
    "TRIGGER_RECENT_SECONDS",
    "TRIGGER_TOUCH_THROTTLE_S",
    "VIEWER_PRESENT_SECONDS",
]
