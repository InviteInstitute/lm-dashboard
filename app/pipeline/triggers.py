"""
The sustained inactive trigger that feeds the dashboard's "who needs help" column.

  inactive : no event for at least INACTIVE_TRIGGER_SECONDS.

The four momentary edit-distance triggers (wheel_spin, resilience, explorer,
iterative) live in the shared learner_models engine and fire from the worker the
instant a run lands (workers.recompute_and_write), deduped per type by run index.
Only inactive is sustained and evaluated by the per-tick sweep here (evaluate).
Acknowledged rows drop out of the feed.
"""

import logging
from datetime import timedelta

from app import db

log = logging.getLogger("pipeline")

# Thresholds + labels live in app/constants.py. RE_ALERT_SECONDS rotates an
# acked-but-still-holding sustained trigger so a student who never got unstuck
# resurfaces.
from app.constants import (
    INACTIVE_TRIGGER_SECONDS,
    RE_ALERT_SECONDS,
    TRIGGER_TOUCH_THROTTLE_S,
)
from app.constants import (
    TRIGGER_LABELS as LABELS,
)


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

    # Batched sweep: two reads (all states + all open inactive rows) up front, one
    # pass building create/resolve/touch batches, one atomic flush -- so the whole
    # sweep is a handful of statements regardless of cohort size, instead of a
    # SELECT (and often a write) per student every tick.
    ttype = "inactive"
    open_by_sid = db.open_triggers_by_student(ttype)
    creates, resolves, touches = [], [], []

    for s in db.all_student_states():
        sid = s["studentID"]
        last = s["last_event_time"]
        idle = (now - last).total_seconds() if last else None
        is_inactive = (
            idle is not None and idle >= INACTIVE_TRIGGER_SECONDS and ttype not in disabled
        )
        ev = open_by_sid.get(sid)
        detail = {"label": LABELS[ttype], "value": _fmt_idle(idle)}

        if is_inactive and ev is None:
            started = last + timedelta(seconds=INACTIVE_TRIGGER_SECONDS) if last else now
            creates.append((sid, ttype, started, now, detail))
        elif is_inactive and ev is not None:
            # Acked but still holding past the re-alert window: resolve the acked
            # row and open a fresh, unacked one so the student comes back to the
            # feed. Otherwise just keep the row fresh -- but throttle that touch,
            # since the idle-time display is minute-granular and doesn't need a
            # write every half-second tick.
            if ev["acknowledged"] and (now - ev["started_at"]).total_seconds() >= RE_ALERT_SECONDS:
                resolves.append((ev["id"], now))
                creates.append((sid, ttype, now, now, detail))
            elif (now - ev["last_seen_at"]).total_seconds() >= TRIGGER_TOUCH_THROTTLE_S:
                touches.append((ev["id"], now, detail))
        elif not is_inactive and ev is not None:
            resolves.append((ev["id"], now))

    db.apply_sustained_sweep(creates, resolves, touches)
