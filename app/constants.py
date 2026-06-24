"""
Central tunables for the dashboard backend -- the knobs you'd actually change.
One home for the strategy-state codes, trigger thresholds, and size/time limits
that were previously duplicated across main.py, workers.py and triggers.py.

Domain-specific constants stay next to the code that owns them:
  - episode segmentation thresholds -> app/episode_engine/pipeline_config.py
  - HMM model constants             -> app/strategy_hmm/constants.py
This file is for the cross-cutting, app-level values.
"""

# --- strategy (HMM) states ---
STUCK_STATE = 2                       # the "stuck" / wheel-spinning HMM state
STATE_LABELS = {0: "iterator", 1: "explorer", 2: "stuck"}

# --- triggers ---
TRIGGER_LABELS = {"wheel_spin": "Wheel-spinning", "inactive": "Inactive", "big_change": "Big rewrite"}
SUSTAINED_TRIGGERS = ("wheel_spin", "inactive")   # the rest (big_change) fire-and-resolve at once
INACTIVE_SECONDS = 300                # 5 min idle -> "inactive"; matches the segmenter's INACTIVE_PAUSE
BIG_CHANGE_SCORE = 0.5                # APTED change_score at/above this fires "big rewrite"
RE_ALERT_SECONDS = 600                # re-open an acked sustained trigger still holding after 10 min
TRIGGER_RECENT_SECONDS = 120          # a resolved trigger lingers in the feed this long (2 min)

# --- limits / timing ---
MAX_STUDENT_IDS = 500                 # cap on ?students= ids per request (under SQLite's variable limit)
BUFFER_MAX = 5000                     # per-student in-memory rolling event history
PAUSED_POLL_S = 1.0                   # how often the paused daemon re-checks the resume flag
