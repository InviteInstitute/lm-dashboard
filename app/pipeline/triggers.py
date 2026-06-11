"""
Intervention triggers for the live feed.

Three simple, threshold-based rules evaluated each tick over all students:

  wheel_spin : HMM current state == stuck (re-running with no change)
  inactive   : no event for >= INACTIVE_SECONDS
  big_change : latest run's change_score >= BIG_CHANGE_SCORE (tossed/rewrote work)

Sustained triggers (wheel_spin, inactive) stay open while the condition holds
and resolve when it clears. big_change is momentary: one event per qualifying
run. Acknowledged rows leave the feed.
"""
import logging
from datetime import timedelta

from app import db

log = logging.getLogger("pipeline")

# -- thresholds (set from observed data + your choices) --
WHEEL_SPIN_STATE = 2
INACTIVE_SECONDS = 300        # 5 min, matches segmenter INACTIVE_PAUSE
BIG_CHANGE_SCORE = 0.5

LABELS = {"wheel_spin": "Wheel-spinning", "inactive": "Inactive", "big_change": "Big rewrite"}
SUSTAINED = ("wheel_spin", "inactive")


def _fmt_idle(secs):
    m = int((secs or 0) // 60)
    if m < 60:
        return f"idle {m}m"
    if m < 1440:
        return f"idle {m // 60}h"
    return f"idle {m // 1440}d"


def _latest_run(state):
    runs = (state.get("runs") or {}).get("runs", [])
    return runs[-1] if runs else None


def evaluate(now=None):
    """One full pass over student_state; opens/updates/resolves trigger_events."""
    now = now or db.now()
    fired = 0
    for s in db.all_student_states():
        sid = s["studentID"]

        # ---- wheel_spin: HMM says stuck ----
        _sustain(sid, "wheel_spin",
                 active=(s["current_state"] == WHEEL_SPIN_STATE),
                 now=now, started=now,
                 detail={"label": LABELS["wheel_spin"],
                         "value": f'{s["consecutive_stuck"]} re-runs'})

        # ---- inactive: idle past threshold ----
        idle = None
        if s["last_event_time"]:
            idle = (now - s["last_event_time"]).total_seconds()
        is_inactive = idle is not None and idle >= INACTIVE_SECONDS
        _sustain(sid, "inactive",
                 active=is_inactive, now=now,
                 started=(s["last_event_time"] + timedelta(seconds=INACTIVE_SECONDS)
                          if s["last_event_time"] else now),
                 detail={"label": LABELS["inactive"], "value": _fmt_idle(idle)})

        # ---- big_change: momentary, one per qualifying run ----
        run = _latest_run(s)
        if run and run.get("change_score") is not None and run["change_score"] >= BIG_CHANGE_SCORE:
            idx = run.get("index")
            if not db.big_change_exists(sid, idx):
                db.create_trigger(
                    sid, "big_change",
                    started_at=now, last_seen_at=now, resolved_at=now,
                    detail={"label": LABELS["big_change"],
                            "value": f"change {run['change_score']:.2f}", "run_index": idx})
                fired += 1
    return fired


def _sustain(student_id, ttype, active, now, started, detail):
    ev = db.current_open_trigger(student_id, ttype)
    if active and ev is None:
        db.create_trigger(student_id, ttype, started_at=started, last_seen_at=now,
                          resolved_at=None, detail=detail)
    elif active and ev is not None:
        db.touch_trigger(ev["id"], now, detail)   # keep acknowledged as-is
    elif not active and ev is not None:
        db.resolve_trigger(ev["id"], now)
