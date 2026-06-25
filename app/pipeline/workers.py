"""
Per-student in-memory workers, the compute side of the daemon.

Each worker keeps a rolling buffer of one student's recent events. When new
events arrive it recomputes that student's derived state, strategy, episodes,
and the playground prompt, and writes it into the student_state table. The
dashboard only ever reads student_state, never the raw logs.

What gets recomputed when: the strategy HMM works at the granularity of a RUN
(a runProject event), so the run sequence is only re-decoded when a new run
lands; episodes and the playground prompt refresh on any new event. The whole
recompute is cheap, on the order of tens of milliseconds per student.
"""
import logging
from collections import deque

from app import db
from app.strategy_hmm.pipeline import compute_strategy_states
from app.strategy_hmm.apted_similarity import clear_cache as clear_score_cache
from app.smart_delta_engine import generate_llm_prompt_from_project
from app.episode_engine import segment_session
from app.pipeline.triggers import BIG_CHANGE_SCORE, LABELS, _disabled_types

logger = logging.getLogger("pipeline")

from app.constants import STUCK_STATE, STATE_LABELS, BUFFER_MAX


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
        """Fold one event into the buffer and update the running fields (class
        code, latest project, last-seen markers). Flags the worker dirty, and
        flags had_new_run when the event is a runProject so the next recompute
        re-decodes the HMM. `ev` is a dict with studentID, classCode, eventType,
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
        and upsert it into student_state. Decodes the strategy HMM (reusing the
        cached decode when no new run arrived), fires any pending big_change
        alerts, segments the session into episodes, rebuilds the playground
        prompt, and clears the dirty flag.

        `disabled` is the set of switched-off trigger types; the daemon passes
        the copy it already fetched this tick, and we fall back to reading it
        ourselves when called without one."""
        if disabled is None:
            disabled = _disabled_types()
        events = list(self.events)

        # Strategy HMM works per run, so only re-decode when a new run arrived;
        # otherwise reuse the last decode.
        if self.had_new_run or self._runs_cache is None:
            self._runs_cache = compute_strategy_states(events)
            self.had_new_run = False
        runs = self._runs_cache["runs"]
        obs_labels = self._runs_cache["obs_labels"]
        run_count = sum(1 for r in runs)  # one entry per runProject

        # Big-change alerts fire once per qualifying run, right when it's decoded.
        # The in-memory dedupe set (seeded from the DB on rehydrate) is what lets
        # this replace the old approach of re-scanning every student's whole
        # history inside triggers.evaluate() each tick. The loop handles a
        # backfill that decodes several runs at once; live, it's just one new
        # run. Respects the disabled-triggers flag.
        if "big_change" not in disabled:
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
    log, the one SQL read on the hot path. Also seeds the big_change dedupe set
    so a restart never re-fires past alerts. db.student_tail already returns
    rows oldest-first, ready to replay in order."""
    worker.fired_big_change = db.big_change_indices(worker.student_id)
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
