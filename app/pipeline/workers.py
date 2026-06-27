"""
Per-student in-memory workers, the compute side of the daemon.

Each worker keeps a rolling buffer of one student's recent events. When new
events arrive it recomputes that student's derived state (the per-run
edit_distance sequence, the momentary triggers it fires, episodes, and the
playground prompt) and writes it into the student_state table. The dashboard
only ever reads student_state, never the raw logs.

What gets recomputed when: the edit_distance sequence is per RUN (a runProject
event), so it is only rebuilt when a new run lands; episodes and the playground
prompt refresh on any new event. The whole recompute is cheap, on the order of
tens of milliseconds per student.
"""
import logging
from collections import deque
from datetime import datetime, timezone

from app import db
from app.runs.run_sequence import compute_run_edit_distances
from app.runs.apted_similarity import clear_cache as clear_score_cache
from app.smart_delta_engine import generate_llm_prompt_from_project
from app.episode_engine import segment_session
from app.pipeline.triggers import detect_run_triggers, _disabled_types

logger = logging.getLogger("pipeline")

from app.constants import BUFFER_MAX

# Trigger types fired per-run from the worker (deduped by run index).
RUN_TRIGGER_TYPES = ("wheel_spin", "resilience", "explorer", "iterative")


class StudentWorker:
    def __init__(self, student_id):
        self.student_id = student_id
        self.class_code = None
        self.events = deque(maxlen=BUFFER_MAX)   # in-memory rolling history
        self.latest_project = None
        self.latest_project_ts = None
        self.last_event_id = 0
        self.last_event_time = None
        self.had_new_run = False
        self.dirty = False
        self._runs_cache = None                  # last run edit-distance sequence
        self.fired = {t: set() for t in RUN_TRIGGER_TYPES}   # run indices already alerted, per type

    # -- ingest ----------------------------------------------------------
    def ingest(self, ev):
        """Fold one event into the buffer and update the running fields (class
        code, latest project, last-seen markers). Flags the worker dirty, and
        flags had_new_run when the event is a runProject so the next recompute
        rebuilds the run sequence. `ev` is a dict with studentID, classCode, eventType,
        raw_message, project, source_event_id, and event_time (a datetime)."""
        et = ev.get("eventType") or ""
        ts = ev["event_time"].timestamp() if ev.get("event_time") else None
        self.events.append({"event_type": et, "content": ev.get("raw_message") or "{}", "ts": ts})
        if ev.get("classCode"):
            self.class_code = ev["classCode"]
        if ev.get("project") is not None:
            self.latest_project = ev["project"]
            self.latest_project_ts = ev.get("event_time")
        if ev.get("source_event_id") is not None:
            self.last_event_id = max(self.last_event_id, ev["source_event_id"])
        if ev.get("event_time"):
            self.last_event_time = ev["event_time"]
        if et == "runProject":
            self.had_new_run = True
        self.dirty = True

    # -- inference + materialize ----------------------------------------
    def recompute_and_write(self, disabled=None):
        """Recompute this student's full derived state from the buffered events
        and upsert it into student_state. Rebuilds the per-run edit_distance
        sequence (reusing the cache when no new run arrived), fires the four
        momentary edit-distance triggers, segments the session into episodes,
        rebuilds the playground prompt, and clears the dirty flag.

        `disabled` is the set of switched-off trigger types; the daemon passes
        the copy it already fetched this tick, and we fall back to reading it
        ourselves when called without one."""
        if disabled is None:
            disabled = _disabled_types()
        events = list(self.events)

        # The edit-distance sequence only changes when a new run arrives; otherwise
        # reuse the last one.
        if self.had_new_run or self._runs_cache is None:
            self._runs_cache = compute_run_edit_distances(events)
            self.had_new_run = False
        runs = self._runs_cache["runs"]
        run_count = len(runs)  # one entry per runProject
        edit_distances = [r["edit_distance"] for r in runs]

        # Momentary triggers fire once per qualifying run. detect_run_triggers is a
        # deterministic pass over the whole sequence, so the per-type fired-index
        # sets (seeded from the DB on rehydrate) keep a backfill or restart from
        # re-firing an old run. Respects the disabled-triggers flag.
        for ttype, idx, detail in detect_run_triggers(edit_distances):
            if ttype in disabled or idx in self.fired[ttype]:
                continue
            run_ts = runs[idx].get("ts")
            at = datetime.fromtimestamp(run_ts, tz=timezone.utc) if run_ts else db.now()
            db.create_trigger(
                self.student_id, ttype,
                started_at=at, last_seen_at=at, resolved_at=at,
                detail={**detail, "run_index": idx})
            self.fired[ttype].add(idx)

        # Episodes (timeline)
        seg_events = [{"event_type": e["event_type"], "ts": e["ts"]} for e in events]
        episodes, pauses = segment_session(seg_events)
        episodes_payload = {
            "events": [{"eventType": e["event_type"]} for e in events],
            "episodes": episodes,
            "pauses": pauses,
            "event_count": len(events),
            "episode_count": len(episodes),
            "pause_count": len(pauses),
        }

        # Playground (current workspace prompt)
        prompt = None
        if self.latest_project:
            try:
                prompt = generate_llm_prompt_from_project(self.latest_project)
            except Exception:
                prompt = None

        db.upsert_student_state(
            self.student_id,
            {
                "classCode": self.class_code,
                "run_count": run_count,
                "event_count": len(events),
                "runs": {"runs": runs, "run_count": run_count},
                "episodes": episodes_payload,
                "playground_prompt": prompt,
                "playground_time": self.latest_project_ts,
                "last_event_id": self.last_event_id,
                "last_event_time": self.last_event_time,
            },
        )
        self.dirty = False


# ---------------------------------------------------------------------------
# Module-level worker registry and the routing/lifecycle helpers around it.
# ---------------------------------------------------------------------------
_workers = {}  # studentID -> StudentWorker


def get_worker(student_id):
    """Return the cached worker for a student, creating and rehydrating one from
    the raw log on first access."""
    w = _workers.get(student_id)
    if w is None:
        w = _workers[student_id] = StudentWorker(student_id)
        _rehydrate(w)
    return w


def route(ev):
    """Hand a freshly-persisted event to its student's worker.

    If that worker doesn't exist yet, we create and rehydrate it instead, and
    crucially do NOT also ingest(ev): rehydrate already reloads the just-inserted
    vex_log row, so ingesting here too would double-count the event in the
    buffer."""
    sid = ev["studentID"]
    w = _workers.get(sid)
    if w is None:
        w = _workers[sid] = StudentWorker(sid)
        _rehydrate(w)
        return
    w.ingest(ev)


def dirty_workers():
    """Every cached worker that took new events since its last recompute."""
    return [w for w in _workers.values() if w.dirty]


def reconcile(tracked):
    """Evict cached workers for any student no longer on the tracked allowlist."""
    for sid in list(_workers.keys()):
        if sid not in tracked:
            _workers.pop(sid, None)


def reset():
    """Evict every cached worker. The daemon calls this on a dashboard reset, so
    that buffered events can't immediately re-materialize the state that was
    just wiped. Also drop the APTED score cache so it doesn't outlive the data."""
    _workers.clear()
    clear_score_cache()


# Session cutoff: when set, workers rehydrate from session-only events so a
# returning student's prior session is hidden (the raw log is left intact). The
# daemon sets this once at startup.
_session_cutoff = None


def set_session_cutoff(since):
    global _session_cutoff
    _session_cutoff = since


def has_worker(student_id):
    return student_id in _workers


def _rehydrate(worker):
    """Warm a cold worker by replaying the student's recent tail from the raw
    log, the one SQL read on the hot path. Also seeds the per-type fired-index
    dedupe sets so a restart never re-fires past alerts. db.student_tail already
    returns rows oldest-first, ready to replay in order."""
    for t in worker.fired:
        worker.fired[t] = db.fired_indices(worker.student_id, t)
    for row in db.student_tail(worker.student_id, BUFFER_MAX, since=_session_cutoff):
        et = row["eventType"] or ""
        ts = None
        if row["event_time"]:
            ts = row["event_time"].timestamp()
        elif row["received_at"]:
            ts = row["received_at"].timestamp()
        worker.events.append({"event_type": et, "content": row["raw_message"] or "{}", "ts": ts})
        if row["classCode"]:
            worker.class_code = row["classCode"]
        if row["project"] is not None:
            worker.latest_project = row["project"]
            worker.latest_project_ts = row["event_time"]
        if row["source_event_id"] is not None:
            worker.last_event_id = max(worker.last_event_id, row["source_event_id"])
        if row["event_time"]:
            worker.last_event_time = row["event_time"]
    if worker.events:
        worker.had_new_run = True
        worker.dirty = True
        logger.info("rehydrated %s with %d events", worker.student_id, len(worker.events))
