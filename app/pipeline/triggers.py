"""
The intervention rules that feed the dashboard's "who needs help" column, all
defined on each run's integer edit_distance (see docs/superpowers/specs/NoHMM.md).

  wheel_spin : >= WHEEL_SPIN_ZERO_RUNS consecutive zero-edit runs (re-running the
               same code); silent until a real edit re-arms it.
  resilience : a real edit right after >= RESILIENCE_ZERO_RUNS zeros (recovered).
  explorer   : a single run with edit_distance >= EXPLORER_EDIT_DISTANCE.
  iterative  : ITERATIVE_DEFAULT_THRESHOLD runs with edit_distance > 1 (steady edits).
  inactive   : no event for at least INACTIVE_TRIGGER_SECONDS.

The four edit-distance triggers are momentary: they fire from the worker the
instant a run lands (detect_run_triggers below, called from
workers.recompute_and_write), deduped per type by run index. Only inactive is
sustained and evaluated by the per-tick sweep here. Acknowledged rows drop out
of the feed.
"""
import logging
from datetime import timedelta

from app import db

log = logging.getLogger("pipeline")

# Thresholds + labels live in app/constants.py; aliased here to the names this
# module (and its tests) already use. RE_ALERT_SECONDS rotates an acked-but-still-
# holding sustained trigger so a student who never got unstuck resurfaces.
from app.constants import (
    INACTIVE_TRIGGER_SECONDS, RE_ALERT_SECONDS, TRIGGER_LABELS as LABELS,
    WHEEL_SPIN_ZERO_RUNS, RESILIENCE_ZERO_RUNS, EXPLORER_EDIT_DISTANCE,
    ITERATIVE_EDIT_MIN, ITERATIVE_DEFAULT_THRESHOLD,
)


def detect_run_triggers(edit_distances, iterative_threshold=ITERATIVE_DEFAULT_THRESHOLD):
    """One pure pass over a per-run edit_distance sequence (first element None).
    Emits (trigger_type, run_index, detail) for each momentary fire. Deterministic,
    so the worker can re-run it and dedupe by run_index without double-firing.

      wheel_spin : a trailing run of edit_distance == 0 reaches WHEEL_SPIN_ZERO_RUNS;
                   silent (cooldown) until a non-zero edit re-arms it.
      resilience : a non-zero edit lands right after >= RESILIENCE_ZERO_RUNS zeros.
      explorer   : a single run with edit_distance >= EXPLORER_EDIT_DISTANCE.
      iterative  : the count of runs with edit_distance > ITERATIVE_EDIT_MIN reaches
                   the threshold; silent until an edit_distance == 0 run resets it.
    """
    out = []
    zero_streak = 0
    wheel_armed = True
    iter_count = 0
    iter_armed = True
    for i, ed in enumerate(edit_distances):
        if ed is None:
            continue
        if ed > 0 and zero_streak >= RESILIENCE_ZERO_RUNS:
            out.append(("resilience", i, {"label": LABELS["resilience"],
                                          "value": f"recovered after {zero_streak} reruns"}))
        if ed == 0:
            zero_streak += 1
            if zero_streak >= WHEEL_SPIN_ZERO_RUNS and wheel_armed:
                out.append(("wheel_spin", i, {"label": LABELS["wheel_spin"],
                                              "value": f"{zero_streak} identical reruns"}))
                wheel_armed = False
        else:
            zero_streak = 0
            wheel_armed = True
        if ed >= EXPLORER_EDIT_DISTANCE:
            out.append(("explorer", i, {"label": LABELS["explorer"], "value": f"changed {ed}"}))
        if ed > ITERATIVE_EDIT_MIN:
            iter_count += 1
            if iter_count >= iterative_threshold and iter_armed:
                out.append(("iterative", i, {"label": LABELS["iterative"],
                                             "value": f"{iter_count} steady edits"}))
                iter_armed = False
        if ed == 0:
            iter_count = 0
            iter_armed = True
    return out


def _fmt_idle(secs):
    m = int((secs or 0) // 60)
    if m < 60:
        return f"idle {m}m"
    if m < 1440:
        return f"idle {m // 60}h"
    return f"idle {m // 1440}d"


def _disabled_types():
    """The set of trigger types the researcher has switched off, read from the
    comma-separated meta flag the API writes. An empty flag means all are on."""
    raw = db.get_meta("disabled_triggers") or ""
    return {t for t in raw.split(",") if t}


def evaluate(now=None, disabled=None):
    """One sweep over student_state for the single sustained trigger, inactive:
    open a row when a student goes idle past INACTIVE_TRIGGER_SECONDS, keep it
    fresh while idle, and resolve it when a new event arrives. The four momentary
    edit-distance triggers are not handled here -- they fire from the worker the
    moment a run lands (see workers.recompute_and_write).

    `disabled` is the set of switched-off trigger types; the daemon passes the
    copy it already fetched this tick, and we fall back to reading it ourselves
    when called without one."""
    now = now or db.now()
    if disabled is None:
        disabled = _disabled_types()
    for s in db.all_student_states():
        sid = s["studentID"]
        idle = (now - s["last_event_time"]).total_seconds() if s["last_event_time"] else None
        is_inactive = (idle is not None and idle >= INACTIVE_TRIGGER_SECONDS
                       and "inactive" not in disabled)
        _sustain(sid, "inactive",
                 active=is_inactive, now=now,
                 started=(s["last_event_time"] + timedelta(seconds=INACTIVE_TRIGGER_SECONDS)
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
