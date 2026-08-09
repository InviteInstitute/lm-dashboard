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
from datetime import UTC, datetime

from app import db
from app.episode_engine import segment_session
from app.pipeline.switches import detect_switches
from app.pipeline.triggers import _disabled_types, detect_run_triggers_by_playground
from app.runs.apted_similarity import clear_cache as clear_score_cache
from app.runs.run_sequence import compute_run_edit_distances
from app.smart_delta_engine import generate_llm_prompt_from_project

logger = logging.getLogger("pipeline")

from app.constants import BUFFER_MAX

# Trigger types fired per-run from the worker (deduped by run index).
RUN_TRIGGER_TYPES = ("wheel_spin", "resilience", "explorer", "iterative")


class StudentWorker:
    def __init__(self, student_id):
        self.student_id = db.canon_id(student_id)  # canonical (folded) key for all writes
        self.class_code = None
        self.display_id = None  # most-recent studentID casing seen live
        self.events = deque(maxlen=BUFFER_MAX)  # in-memory rolling history
        self.latest_project = None
        self.latest_project_ts = None
        self.last_event_id = 0
        self.last_event_time = None
        self.had_new_run = False
        self.dirty = False
        self._runs_cache = None  # last run edit-distance sequence
        self.fired = {t: set() for t in RUN_TRIGGER_TYPES}  # run indices already alerted, per type

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
        # Switch detection: compare this event's casing/class against the
        # last-seen ones BEFORE we overwrite them. Only tracked students have a
        # worker, so this is roster-only for free. Non-critical telemetry, so a
        # failure here must never break ingest.
        for kind, frm, to in detect_switches(
            self.display_id, self.class_code, ev.get("studentID"), ev.get("classCode")
        ):
            try:
                db.record_switch(self.student_id, kind, frm, to)
            except Exception:
                logger.exception("record_switch failed for %s", self.student_id)
        if ev.get("studentID"):
            self.display_id = ev["studentID"]
        if ev.get("classCode"):
            self.class_code = ev["classCode"]
        if ev.get("project") is not None:
            # Monotonic in event-time: with the case-insensitive fold, two
            # devices (with disagreeing clocks) can feed one worker, so "last
            # to arrive" is not "last to happen". An out-of-order older
            # snapshot must not roll the playground view backwards. A missing
            # timestamp on either side can't be compared, so it still accepts.
            ts_new = ev.get("event_time")
            if self.latest_project_ts is None or ts_new is None or ts_new >= self.latest_project_ts:
                self.latest_project = ev["project"]
                self.latest_project_ts = ts_new
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

        # Momentary triggers fire once per qualifying run, evaluated per contiguous
        # playground stretch so a challenge switch resets every counter and applies
        # that playground's threshold. Deduped per type by run index (seeded from the
        # DB on rehydrate), so a backfill or restart can't re-fire an old run.
        # Respects the disabled-triggers flag.
        for ttype, idx, detail in detect_run_triggers_by_playground(runs):
            if ttype in disabled or idx in self.fired[ttype]:
                continue
            run_ts = runs[idx].get("ts")
            at = datetime.fromtimestamp(run_ts, tz=UTC) if run_ts else db.now()
            db.create_trigger(
                self.student_id,
                ttype,
                started_at=at,
                last_seen_at=at,
                resolved_at=at,
                detail={**detail, "run_index": idx},
            )
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
                "display_id": self.display_id or self.student_id,
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
    the raw log on first access. Keyed on the canonical id so every casing of a
    handle shares one worker."""
    key = db.canon_id(student_id)
    w = _workers.get(key)
    if w is None:
        w = _workers[key] = StudentWorker(student_id)
        _rehydrate(w)
    return w


def route(ev):
    """Hand a freshly-persisted event to its student's worker.

    If that worker doesn't exist yet, we create and rehydrate it instead, and
    crucially do NOT also ingest(ev): rehydrate already reloads the just-inserted
    vex_log row, so ingesting here too would double-count the event in the
    buffer."""
    key = db.canon_id(ev["studentID"])
    w = _workers.get(key)
    if w is None:
        w = _workers[key] = StudentWorker(ev["studentID"])
        _rehydrate(w)
        return
    w.ingest(ev)


def dirty_workers():
    """Every cached worker that took new events since its last recompute."""
    return [w for w in _workers.values() if w.dirty]


def reconcile(tracked):
    """Evict cached workers for any student no longer on the tracked allowlist.
    `tracked` may hold raw casings, so fold both sides to the canonical key."""
    keep = {db.canon_id(t) for t in tracked}
    for key in list(_workers.keys()):
        if key not in keep:
            _workers.pop(key, None)


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
    return db.canon_id(student_id) in _workers


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
        if row.get("studentID"):
            worker.display_id = row[
                "studentID"
            ]  # rows are oldest-first, so this ends on the newest casing
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
