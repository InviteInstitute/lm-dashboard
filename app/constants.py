"""
The backend's tunable numbers.

The trigger thresholds and labels belong to the shared engine
(learner_models.constants, in the agent-lm-packages submodule), so the ones the
dashboard reads are re-exported from there rather than copied, and cannot drift
from the engine that computes on them. The dashboard's own knobs (feed timing,
buffer size, the cursor name) are defined here. Settings from the environment
live in config.py.
"""

# Re-exported for the app's own readers (triggers.py, main.py).
from learner_models.constants import (  # noqa: F401
    INACTIVE_TRIGGER_SECONDS,
    RE_ALERT_SECONDS,
    TRIGGER_LABELS,
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
