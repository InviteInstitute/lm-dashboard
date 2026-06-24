"""
The intervention rules that feed the dashboard's "who needs help" column.

There are three, all threshold-based:

  wheel_spin : the HMM's current state is "stuck" (re-running with no real change)
  inactive   : no event for at least INACTIVE_SECONDS
  big_change : a run's change_score is at least BIG_CHANGE_SCORE (work tossed/rewritten)

The two sustained rules, wheel_spin and inactive, stay open as long as their
condition holds and resolve once it clears; this module evaluates them on every
tick. big_change is momentary, one alert per qualifying run, and is fired from
the worker the instant a run is decoded rather than from the sweep here.
Acknowledged rows drop out of the feed.
"""
import logging
from datetime import datetime, timedelta, timezone

from app import db

log = logging.getLogger("pipeline")

# -- thresholds (tuned from observed data + chosen defaults) --
WHEEL_SPIN_STATE = 2
INACTIVE_SECONDS = 300        # 5 min; lines up with the segmenter's INACTIVE_PAUSE
BIG_CHANGE_SCORE = 0.5
# Re-alert window. Once a TA acks a sustained trigger, if the condition is still
# holding this long after the alert first started, the trigger is rotated: the
# acked row is resolved and a fresh one opened, so a student who never actually
# got unstuck resurfaces in the feed instead of staying silently dismissed.
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


def _wheel_spin_started(state, fallback):
    """Find when the student's current stuck streak began.

    Walks the runs from newest to oldest while they stay in the STUCK state and
    returns the timestamp of the earliest run in that unbroken streak, so the
    alert's age reflects how long they've actually been stuck rather than when we
    noticed. Returns `fallback` (the caller passes now) if no run timestamps are
    available."""
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
    """The set of trigger types the researcher has switched off, read from the
    comma-separated meta flag the API writes. An empty flag means all are on."""
    raw = db.get_meta("disabled_triggers") or ""
    return {t for t in raw.split(",") if t}


def evaluate(now=None, disabled=None):
    """One sweep over student_state for the sustained triggers (wheel_spin and
    inactive), opening, touching, and resolving trigger_event rows as conditions
    change. A type that's been disabled is treated as inactive, so its open rows
    resolve and clear from the feed within a tick. big_change is not handled here:
    it's momentary and fires from the worker the moment a run is decoded (see
    workers.recompute_and_write).

    `disabled` is the set of switched-off trigger types; the daemon passes the
    copy it already fetched this tick, and we fall back to reading it ourselves
    when called without one."""
    now = now or db.now()
    if disabled is None:
        disabled = _disabled_types()
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


def _sustain(student_id, ttype, active, now, started, detail):
    """Reconcile one open trigger row against the current condition: open a new
    one when the condition starts, keep an existing one fresh while it holds,
    rotate an acked-but-still-holding one past the re-alert window, and resolve
    it when the condition clears."""
    ev = db.current_open_trigger(student_id, ttype)
    if active and ev is None:
        db.create_trigger(student_id, ttype, started_at=started, last_seen_at=now,
                          resolved_at=None, detail=detail)
    elif active and ev is not None:
        # Acked but still holding past the re-alert window: resolve the acked row
        # and open a fresh, unacked one so the student comes back to the feed.
        # Without this a persistently stuck student would never alert again until
        # they left and re-entered the state.
        if ev["acknowledged"] and (now - ev["started_at"]).total_seconds() >= RE_ALERT_SECONDS:
            db.resolve_trigger(ev["id"], now)
            db.create_trigger(student_id, ttype, started_at=now, last_seen_at=now,
                              resolved_at=None, detail=detail)
        else:
            db.touch_trigger(ev["id"], now, detail)
    elif not active and ev is not None:
        db.resolve_trigger(ev["id"], now)
