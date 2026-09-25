"""
Per-student in-memory workers, the compute side of the daemon.

Each worker keeps a rolling buffer of one student's recent events. When new
events arrive it recomputes that student's derived state (the per-run
edit_distance sequence, the momentary triggers it fires, episodes, and the
playground prompt) and writes it into the student_state table. The dashboard
only ever reads student_state, never the raw logs.

Every event is folded into three incremental engine streams as it arrives (the
per-run edit distances, the episode segmenter and the goal profiles), so a
recompute reads their current state instead of re-deriving it from the whole
buffer. The run sequence and episodes are indexed from the worker's first event,
the same way the goal stream is, so all three stay joined after the rolling
buffer wraps. The whole recompute is cheap, on the order of milliseconds per
student.
"""

import json
import logging
from collections import deque
from datetime import UTC, datetime

from goal_strategy import GoalProfileStream
from learner_models import (
    RunDistanceStream,
    SessionSegmenter,
    detect_run_triggers_by_playground,
    detect_switches,
)
from learner_models import (
    clear_cache as clear_score_cache,
)
from log_parser_delta_engine import generate_compact_prompt_from_project

from app import db
from app.config import (
    GOAL_BATTERY_ENABLED,
    GOAL_RECOGNITION_ENABLED,
    GOAL_ROLLUP_ENABLED,
    GOAL_RUBRIC_ENABLED,
    GOAL_TIMELINE_ENABLED,
)
from app.pipeline.triggers import _disabled_types

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
        self.dirty = False
        self.run_stream = RunDistanceStream()  # per-run edit distances, fed every event
        self.segmenter = SessionSegmenter()  # episodes + pauses, fed every event
        self.fired = {t: set() for t in RUN_TRIGGER_TYPES}  # run indices already alerted, per type
        # Real-time goal recognition: one stream per student, fed every event
        # (rehydrate + ingest) so its run indices line up with the edit-distance
        # runs above. goal_written dedupes the per-run upsert into goal_profile.
        self.gstream = (
            GoalProfileStream(
                session_id=self.student_id,
                include_timeline=GOAL_TIMELINE_ENABLED,
                include_battery=GOAL_BATTERY_ENABLED,
                include_rollup=GOAL_ROLLUP_ENABLED,
                include_rubric=GOAL_RUBRIC_ENABLED,
            )
            if GOAL_RECOGNITION_ENABLED
            else None
        )
        self.goal_written = set()  # run indices already persisted to goal_profile

    def _feed(self, evt):
        """Fold one buffered event ({event_type, content, ts}) into the buffer and
        every incremental stream, in lockstep so their run and event indices line
        up. Called by ingest and rehydrate alike."""
        self.events.append(evt)
        self.run_stream.push(evt)
        self.segmenter.push(evt["event_type"], evt["ts"])
        self._feed_goal(evt)

    def _feed_goal(self, evt):
        """Push one buffered event ({event_type, content, ts}) into the goal
        stream, and pair a playgroundData outcome (weight_cleared, GPS, ...) with
        the run it belongs to. Non-critical, exactly like switch detection: a
        failure here must never break ingest or rehydrate."""
        if self.gstream is None:
            return
        try:
            self.gstream.push(evt)
            if evt.get("event_type") == "playgroundData":
                self._associate_outcome(evt)
        except Exception:
            logger.exception("goal_strategy feed failed for %s", self.student_id)

    def _associate_outcome(self, evt):
        """A playgroundData event reports the playground state after the latest
        run, so its {playground, parameters} outcome belongs to the most recent
        profiled run. Re-profiling that run with the outcome turns the
        outcome-channel indicators (weight_cleared, on-island GPS) from
        'absent'/'unavailable' into real evidence."""
        idx = len(self.gstream.runs) - 1
        if idx < 0:
            return  # outcome before any run — nothing to attach it to
        content = evt.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (ValueError, TypeError):
                return
        outcome = (content or {}).get("playgroundData") if isinstance(content, dict) else None
        if not isinstance(outcome, dict):
            return
        self.gstream.associate_outcome(idx, {"playground_data": outcome})
        self.goal_written.discard(idx)  # force recompute_and_write to re-persist with the outcome

    # -- ingest ----------------------------------------------------------
    def ingest(self, ev):
        """Fold one event into the buffer and streams and update the running fields
        (class code, latest project, last-seen markers), then flag the worker
        dirty. `ev` is a dict with studentID, classCode, eventType, raw_message,
        project, source_event_id, and event_time (a datetime)."""
        et = ev.get("eventType") or ""
        ts = ev["event_time"].timestamp() if ev.get("event_time") else None
        evt = {"event_type": et, "content": ev.get("raw_message") or "{}", "ts": ts}
        self._feed(evt)
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
        self.dirty = True

    # -- inference + materialize ----------------------------------------
    def recompute_and_write(self, disabled=None):
        """Materialize this student's derived state into student_state: the per-run
        edit_distance sequence and episodes the streams already hold, the four
        momentary edit-distance triggers they fire, and the playground prompt.
        Clears the dirty flag.

        `disabled` is the set of switched-off trigger types; the daemon passes
        the copy it already fetched this tick, and we fall back to reading it
        ourselves when called without one."""
        if disabled is None:
            disabled = _disabled_types()
        runs = self.run_stream.runs
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
                # run_index is only meaningful inside one daemon session, so the
                # dedupe key is (session, run_index).
                detail={**detail, "run_index": idx, "session": session_key()},
            )
            self.fired[ttype].add(idx)

        # Episodes (timeline), over the same window the rolling buffer holds.
        self.segmenter.forget_before(self.segmenter.count - len(self.events))
        episodes, pauses = self.segmenter.result()
        episodes_payload = {
            "episodes": episodes,
            "pauses": pauses,
            "event_count": len(self.events),
            "episode_count": len(episodes),
            "pause_count": len(pauses),
        }

        # Playground (current workspace prompt)
        prompt = None
        if self.latest_project:
            try:
                prompt = generate_compact_prompt_from_project(self.latest_project)
            except Exception:
                prompt = None

        db.upsert_student_state(
            self.student_id,
            {
                "display_id": self.display_id or self.student_id,
                "classCode": self.class_code,
                "run_count": run_count,
                "event_count": len(self.events),
                "runs": {"runs": runs, "run_count": run_count},
                "episodes": episodes_payload,
                "playground_prompt": prompt,
                "playground_time": self.latest_project_ts,
                "last_event_id": self.last_event_id,
                "last_event_time": self.last_event_time,
            },
        )

        # Goal evidence: persist each newly-profiled Castle Crashers run once.
        # The goal stream and the run stream are fed the same events, so
        # run_index joins the edit-distance runs above.
        # Unsupported playgrounds (status != "profiled") are skipped, per the
        # Castle-Crashers-only gate. Non-critical: never break the materialize.
        # Once a run is stored, the stream releases it (its result and inputs are
        # the bulk of a worker's memory), except the latest: a playgroundData
        # outcome that arrives next re-profiles it.
        if self.gstream is not None:
            latest = len(self.gstream.runs) - 1
            for gr in self.gstream.runs:
                if gr is None:
                    continue  # already stored and released
                idx = gr.get("index")
                if idx is None:
                    continue
                if idx not in self.goal_written and gr.get("status") == "profiled":
                    try:
                        db.upsert_goal_profile(self.student_id, idx, gr, session=session_key())
                        self.goal_written.add(idx)
                    except Exception:
                        logger.exception(
                            "upsert_goal_profile failed for %s run %s", self.student_id, idx
                        )
                        continue
                if idx < latest and (idx in self.goal_written or gr.get("status") != "profiled"):
                    self.gstream.release(idx)

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


def evict(student_id):
    """Drop one student's cached worker so the next get_worker rebuilds it from
    the raw log, in time order."""
    _workers.pop(db.canon_id(student_id), None)


def reset():
    """Evict every cached worker. The daemon calls this on a dashboard reset, so
    that buffered events can't immediately re-materialize the state that was
    just wiped. Also drop the APTED score cache so it doesn't outlive the data."""
    _workers.clear()
    clear_score_cache()


# Session cutoff: when set, workers rehydrate from session-only events so a
# returning student's prior session is hidden (the raw log is left intact). The
# daemon sets this once at startup.
#
# A run's index is its position in the session's replay, so it restarts at 0
# every session. Everything keyed by run index (stored goal profiles, the alert
# dedupe) is therefore also keyed by session_key(), or a restart would overwrite
# an earlier session's run 0 and never alert on a reused index.
_session_cutoff = None


def set_session_cutoff(since):
    global _session_cutoff
    _session_cutoff = since


def session_key():
    """The current session's identity: its cutoff as a DB timestamp string, or
    "" when there is no cutoff (tests, one-off tools)."""
    return db.dt_to_db(_session_cutoff) if _session_cutoff is not None else ""


def start_session(since):
    """Begin a new session at `since`: set the cutoff and publish its key so the
    API process shows this session's goal evidence only."""
    set_session_cutoff(since)
    db.set_meta(db.SESSION_META_KEY, session_key())


def has_worker(student_id):
    return db.canon_id(student_id) in _workers


def _rehydrate(worker):
    """Warm a cold worker by replaying the student's recent tail from the raw
    log, the one SQL read on the hot path. Also seeds the per-type fired-index
    dedupe sets so a restart never re-fires past alerts. db.student_tail already
    returns rows oldest-first, ready to replay in order."""
    for t in worker.fired:
        worker.fired[t] = db.fired_indices(worker.student_id, t, session=session_key())
    for row in db.student_tail(worker.student_id, BUFFER_MAX, since=_session_cutoff):
        et = row["eventType"] or ""
        ts = None
        if row["event_time"]:
            ts = row["event_time"].timestamp()
        elif row["received_at"]:
            ts = row["received_at"].timestamp()
        evt = {"event_type": et, "content": row["raw_message"] or "{}", "ts": ts}
        worker._feed(evt)
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
        worker.dirty = True
        logger.info("rehydrated %s with %d events", worker.student_id, len(worker.events))
