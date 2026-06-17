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
from datetime import datetime, timedelta, timezone

from app import db

log = logging.getLogger("pipeline")

# -- thresholds (set from observed data + your choices) --
WHEEL_SPIN_STATE = 2
INACTIVE_SECONDS = 300        # 5 min, matches segmenter INACTIVE_PAUSE
BIG_CHANGE_SCORE = 0.5
# After a TA acknowledges a sustained trigger, if the condition keeps holding
# for this long the trigger is rotated: the acked row is resolved and a fresh
# row is opened so the feed re-surfaces a student who never actually got
# unstuck.
RE_ALERT_SECONDS = 600        # 10 min

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


def _wheel_spin_started(state, fallback):
    """When did the student enter their current stuck streak?

    Looks back through runs while they're STUCK and returns the timestamp of
    the first run in that consecutive streak. Falls back to `fallback` (now)
    when run timestamps aren't available."""
    runs = (state.get("runs") or {}).get("runs", [])
    streak_start_ts = None
    for r in reversed(runs):
        if r.get("hmm_state") != WHEEL_SPIN_STATE:
            break
        if r.get("ts") is not None:
            streak_start_ts = r["ts"]
    if streak_start_ts is None:
        return fallback
    try:
        return datetime.fromtimestamp(streak_start_ts, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return fallback


def _disabled_types():
    """Trigger types the researcher has switched off (meta flag, set via the API).
    Comma-separated; empty means all enabled."""
    raw = db.get_meta("disabled_triggers") or ""
    return {t for t in raw.split(",") if t}


def evaluate(now=None):
    """One full pass over student_state; opens/updates/resolves trigger_events.
    Disabled trigger types are not fired; a disabled sustained type also resolves
    any open rows (active=False) so it clears from the feed within a tick."""
    now = now or db.now()
    disabled = _disabled_types()
    fired = 0
    for s in db.all_student_states():
        sid = s["studentID"]

        # ---- wheel_spin: HMM says stuck ----
        wheel_active = s["current_state"] == WHEEL_SPIN_STATE and "wheel_spin" not in disabled
        _sustain(sid, "wheel_spin",
                 active=wheel_active,
                 now=now,
                 started=_wheel_spin_started(s, now) if wheel_active else now,
                 detail={"label": LABELS["wheel_spin"],
                         "value": f'{s["consecutive_stuck"]} re-runs'})

        # ---- inactive: idle past threshold ----
        idle = None
        if s["last_event_time"]:
            idle = (now - s["last_event_time"]).total_seconds()
        is_inactive = (idle is not None and idle >= INACTIVE_SECONDS
                       and "inactive" not in disabled)
        _sustain(sid, "inactive",
                 active=is_inactive, now=now,
                 started=(s["last_event_time"] + timedelta(seconds=INACTIVE_SECONDS)
                          if s["last_event_time"] else now),
                 detail={"label": LABELS["inactive"], "value": _fmt_idle(idle)})

        # ---- big_change: momentary, one per qualifying run ----
        # Scan every run -- not just runs[-1] -- so backfills / batch decodes
        # don't drop big_change events for intermediate qualifying runs.
        if "big_change" in disabled:
            continue
        for run in (s.get("runs") or {}).get("runs", []):
            score = run.get("change_score")
            if score is None or score < BIG_CHANGE_SCORE:
                continue
            idx = run.get("index")
            if db.big_change_exists(sid, idx):
                continue
            db.create_trigger(
                sid, "big_change",
                started_at=now, last_seen_at=now, resolved_at=now,
                detail={"label": LABELS["big_change"],
                        "value": f"change {score:.2f}", "run_index": idx})
            fired += 1
    return fired


def _sustain(student_id, ttype, active, now, started, detail):
    ev = db.current_open_trigger(student_id, ttype)
    if active and ev is None:
        db.create_trigger(student_id, ttype, started_at=started, last_seen_at=now,
                          resolved_at=None, detail=detail)
    elif active and ev is not None:
        # If a TA has acked but the condition keeps holding past RE_ALERT_SECONDS,
        # close the acked row and open a fresh unacked one so the student
        # re-surfaces in the feed -- otherwise a persistently stuck student
        # never alerts again until they leave + re-enter the state.
        if ev["acknowledged"] and (now - ev["started_at"]).total_seconds() >= RE_ALERT_SECONDS:
            db.resolve_trigger(ev["id"], now)
            db.create_trigger(student_id, ttype, started_at=now, last_seen_at=now,
                              resolved_at=None, detail=detail)
        else:
            db.touch_trigger(ev["id"], now, detail)
    elif not active and ev is not None:
        db.resolve_trigger(ev["id"], now)
