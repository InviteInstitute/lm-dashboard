"""
Per-student workers. Each holds the student's recent events in memory and,
when fed new events, recomputes derived state and materializes it into the
student_state table. The viewer reads student_state only -- never raw logs.

Inference policy: the strategy HMM's unit is the RUN (runProject). We re-decode
a student's run sequence the moment a new run lands; episodes + playground
refresh on any new event. All cheap (~40ms/student).
"""
import logging
from collections import deque

from app import db
from app.strategy_hmm.pipeline import compute_strategy_states
from app.smart_delta_engine import generate_llm_prompt_from_project
from app.episode_engine import segment_session
from app.pipeline.triggers import BIG_CHANGE_SCORE, LABELS, _disabled_types

logger = logging.getLogger("pipeline")

STUCK_STATE = 2
STATE_LABELS = {0: "iterator", 1: "explorer", 2: "stuck"}
BUFFER_MAX = 5000


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
        self._runs_cache = None                  # last strategy result (runs+labels)
        self.fired_big_change = set()            # run indices already alerted (in-memory dedupe)

    # -- ingest ----------------------------------------------------------
    def ingest(self, ev):
        """ev: dict with studentID, classCode, eventType, raw_message, project,
        source_event_id, event_time(datetime)."""
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
    def recompute_and_write(self):
        events = list(self.events)

        # HMM (runs) -- only re-decode when a new run arrived (else reuse).
        if self.had_new_run or self._runs_cache is None:
            self._runs_cache = compute_strategy_states(events)
            self.had_new_run = False
        runs = self._runs_cache["runs"]
        obs_labels = self._runs_cache["obs_labels"]
        run_count = sum(1 for r in runs)  # one entry per runProject

        # Big-change alerts: fire once per qualifying run, the moment it's
        # decoded. In-memory dedupe (seeded from the DB on rehydrate) replaces
        # the old per-tick scan over every student's full history in
        # triggers.evaluate(). The loop covers backfills (several runs at once);
        # the live case is one new run. Honors the daemon-side disable flag.
        if "big_change" not in _disabled_types():
            ts = db.now()
            for r in runs:
                idx, score = r.get("index"), r.get("change_score")
                if (idx is not None and score is not None
                        and score >= BIG_CHANGE_SCORE
                        and idx not in self.fired_big_change):
                    db.create_trigger(
                        self.student_id, "big_change",
                        started_at=ts, last_seen_at=ts, resolved_at=ts,
                        detail={"label": LABELS["big_change"],
                                "value": f"change {score:.2f}", "run_index": idx})
                    self.fired_big_change.add(idx)

        states = [r["hmm_state"] for r in runs if r["hmm_state"] is not None]
        current_state = states[-1] if states else None
        consecutive_stuck = 0
        for s in reversed(states):
            if s == STUCK_STATE:
                consecutive_stuck += 1
            else:
                break

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
                "current_state": current_state,
                "state_label": STATE_LABELS.get(current_state),
                "stuck": current_state == STUCK_STATE,
                "consecutive_stuck": consecutive_stuck,
                "run_count": run_count,
                "event_count": len(events),
                "runs": {"runs": runs, "obs_labels": obs_labels, "run_count": run_count},
                "episodes": episodes_payload,
                "playground_prompt": prompt,
                "playground_time": self.latest_project_ts,
                "last_event_id": self.last_event_id,
                "last_event_time": self.last_event_time,
            },
        )
        self.dirty = False


# ---------------------------------------------------------------------------
# Registry + routing
# ---------------------------------------------------------------------------
_workers = {}


def get_worker(student_id):
    w = _workers.get(student_id)
    if w is None:
        w = _workers[student_id] = StudentWorker(student_id)
        _rehydrate(w)
    return w


def route(ev):
    """Route a freshly-persisted event to its student worker.

    If the worker isn't cached yet, _rehydrate already picks up the just-
    inserted vex_log row, so we must NOT also ingest(ev) -- that would
    double-count the same event in the in-memory buffer."""
    sid = ev["studentID"]
    w = _workers.get(sid)
    if w is None:
        w = _workers[sid] = StudentWorker(sid)
        _rehydrate(w)
        return
    w.ingest(ev)


def dirty_workers():
    return [w for w in _workers.values() if w.dirty]


def reconcile(tracked):
    """Drop in-memory workers for students no longer tracked."""
    for sid in list(_workers.keys()):
        if sid not in tracked:
            _workers.pop(sid, None)


def reset():
    """Drop ALL in-memory workers (used by the dashboard reset). Without this,
    a worker's buffered events would re-materialize state right after the wipe."""
    _workers.clear()


def has_worker(student_id):
    return student_id in _workers


def _rehydrate(worker):
    """Cold start: reload a student's tail from raw logs (the only SQL read on
    the hot path). db.student_tail returns rows oldest-first already."""
    worker.fired_big_change = db.big_change_indices(worker.student_id)
    for row in db.student_tail(worker.student_id, BUFFER_MAX):
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
