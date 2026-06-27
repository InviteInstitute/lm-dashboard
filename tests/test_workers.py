"""Per-student workers: edit-distance trigger firing/dedupe, the materialize
write, and the route/rehydrate no-double-count rule."""
from app import db
from app.pipeline import workers


def _worker_with_distances(sid, dists):
    """A worker whose run sequence is pre-seeded with edit_distances (index 0 = None),
    so we can drive recompute_and_write without constructing real VEX XML (the
    edit-distance computation is tested separately)."""
    w = workers.StudentWorker(sid)
    w._runs_cache = {"runs": [{"index": i, "edit_distance": d, "ts": float(i)}
                              for i, d in enumerate(dists)]}
    w.had_new_run = False
    return w


def _fired(ttype):
    return db._query("SELECT json_extract(detail,'$.run_index') i FROM trigger_event "
                     "WHERE trigger_type=?", (ttype,))


def test_wheel_spin_fires_once_and_dedupes_across_recompute():
    w = _worker_with_distances("s1", [None, 0, 0, 0, 0, 0, 0])
    w.recompute_and_write()
    w.recompute_and_write()
    w.recompute_and_write()
    rows = db._query("SELECT 1 FROM trigger_event WHERE trigger_type='wheel_spin'")
    assert len(rows) == 1


def test_explorer_fires_per_big_run():
    w = _worker_with_distances("s1", [None, 13, 2, 20])
    w.recompute_and_write()
    assert sorted(r["i"] for r in _fired("explorer")) == [1, 3]


def test_resilience_fires_on_breakout():
    w = _worker_with_distances("s1", [None, 0, 0, 0, 0, 5])
    w.recompute_and_write()
    assert [r["i"] for r in _fired("resilience")] == [5]


def test_iterative_fires_at_threshold():
    w = _worker_with_distances("s1", [None, 2, 2, 2, 2, 2, 2])
    w.recompute_and_write()
    assert [r["i"] for r in _fired("iterative")] == [6]


def test_disabled_trigger_does_not_fire():
    w = _worker_with_distances("s1", [None, 0, 0, 0, 0, 0, 0])
    w.recompute_and_write(disabled={"wheel_spin"})
    assert db._query("SELECT 1 FROM trigger_event WHERE trigger_type='wheel_spin'") == []


def test_fired_dedupe_seeded_from_db_on_rehydrate():
    # First worker fires explorer at index 1; a fresh worker (restart) seeds its
    # dedupe set from the DB and must not re-fire it.
    _worker_with_distances("s1", [None, 13]).recompute_and_write()
    w2 = workers.StudentWorker("s1")
    for t in w2.fired:
        w2.fired[t] = db.fired_indices("s1", t)
    w2._runs_cache = {"runs": [{"index": 0, "edit_distance": None, "ts": 0.0},
                               {"index": 1, "edit_distance": 13, "ts": 1.0}]}
    w2.had_new_run = False
    w2.recompute_and_write()
    assert len(db._query("SELECT 1 FROM trigger_event WHERE trigger_type='explorer'")) == 1


def test_recompute_writes_run_and_event_counts():
    w = _worker_with_distances("s1", [None])
    w.events.append({"event_type": "runProject", "content": "{}", "ts": 1.0})
    w.events.append({"event_type": "blockMoved", "content": "{}", "ts": 2.0})
    w.recompute_and_write()
    row = db.list_student_states(["s1"])[0]
    assert row["event_count"] == 2 and row["run_count"] == 1


def test_recompute_builds_playground_prompt_from_latest_project():
    import json
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    w = _worker_with_distances("s1", [None])
    w.latest_project = json.dumps({"workspace": xml})
    w.recompute_and_write()
    row = db.list_student_states(["s1"])[0]
    assert row["playground_prompt"] and "[Active]" in row["playground_prompt"]


def test_prompt_generation_failure_falls_back_to_none(monkeypatch):
    # A broken playground prompt must not sink the whole materialize; it degrades
    # to a null prompt and the state still writes.
    def boom(_proj):
        raise ValueError("bad workspace")
    monkeypatch.setattr(workers, "generate_llm_prompt_from_project", boom)
    w = _worker_with_distances("s1", [None])
    w.latest_project = '{"workspace": "<xml/>"}'
    w.recompute_and_write()
    assert db._query("SELECT playground_prompt FROM student_state "
                     "WHERE studentID='s1'")[0]["playground_prompt"] is None


def test_recompute_decodes_real_runs_from_buffered_events():
    """Exercise the real path (no pre-seeded cache): two runProject events with
    workspaces flow through compute_run_edit_distances."""
    import json
    xa = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    xb = ('<xml><block type="events_whenStarted" id="a">'
          '<next><block type="motor_on" id="b"></block></next></block></xml>')
    w = workers.StudentWorker("s1")
    for i, x in enumerate([xa, xb]):
        w.events.append({"event_type": "runProject", "ts": float(i),
                         "content": json.dumps({"project": {"workspace": x}})})
    w.had_new_run = True                            # force a real recompute
    w.recompute_and_write()
    assert db.list_student_states(["s1"])[0]["run_count"] == 2


def test_route_rehydrates_then_does_not_double_count():
    """First event for an uncached student: route() must rehydrate from the DB row
    it was just persisted to, NOT also ingest it (which would double-count)."""
    norm = {
        "raw_message": '{"eventType":"runProject"}', "event_time": db.now(),
        "classCode": "C", "eventType": "runProject", "studentID": "s1",
        "project": "{}", "source_event_id": 1,
    }
    db.insert_message_and_log(norm)
    workers.route(norm)                       # creates worker, rehydrates the 1 row
    assert len(workers.get_worker("s1").events) == 1


def test_reconcile_drops_untracked_workers():
    workers.get_worker("keep")
    workers.get_worker("drop")
    workers.reconcile({"keep"})
    assert workers.has_worker("keep") and not workers.has_worker("drop")


def test_route_to_cached_worker_ingests_without_double_count():
    workers.get_worker("s1")                       # cache it (rehydrates 0 events)
    workers.route({"studentID": "s1", "eventType": "blockMoved", "raw_message": "{}",
                   "project": None, "source_event_id": 1, "event_time": db.now(),
                   "classCode": "C"})
    assert len(workers.get_worker("s1").events) == 1


def test_rehydrate_uses_received_at_when_event_time_missing():
    db.insert_message_and_log({
        "raw_message": '{"eventType":"runProject"}', "event_time": None,
        "classCode": "C", "eventType": "runProject", "studentID": "s1",
        "project": "{}", "source_event_id": 5})
    w = workers.get_worker("s1")                     # cold start -> rehydrate
    assert len(w.events) == 1 and w.events[0]["ts"] is not None


def test_student_tail_replays_chronologically_despite_insertion_order():
    # Backfill persists page_student's newest-first results, so the autoincrement
    # id ends up reverse-chronological. student_tail must still return events
    # oldest-first by event_time, or the run pairing sees negative gaps.
    for eid, ts in [(1, "2026-06-23T12:00:00Z"),    # newer event, inserted FIRST
                    (2, "2026-06-23T08:00:00Z")]:   # older event, inserted second
        db.insert_message_and_log({
            "raw_message": "{}", "event_time": db.db_to_dt(ts), "classCode": "C",
            "eventType": "runProject", "studentID": "s1", "project": "{}",
            "source_event_id": eid})
    times = [e["event_time"] for e in db.student_tail("s1", 10)]
    assert times == sorted(times)      # chronological, not insertion (id) order


def test_student_tail_orders_null_event_time_by_received_at_fallback():
    def _insert(eid, event_time_iso, received_at_iso):
        et = db.dt_to_db(db.db_to_dt(event_time_iso)) if event_time_iso else None
        rt = db.dt_to_db(db.db_to_dt(received_at_iso))
        with db.write_txn() as con:
            cur = con.execute(
                "INSERT INTO message (queue_name, routing_key, exchange, content, received_at) "
                "VALUES ('p', '', '', '{}', ?)", (rt,))
            con.execute(
                "INSERT INTO vex_log (from_message_id, classCode, eventType, studentID, "
                "project, raw_message, event_time, source_event_id) "
                "VALUES (?, 'C', 'runProject', 's1', '{}', '{}', ?, ?)",
                (cur.lastrowid, et, eid))

    _insert(1, "2026-06-23T12:00:00Z", "2026-06-23T12:00:00Z")   # newest
    _insert(2, None,                   "2026-06-23T10:00:00Z")   # middle, null event_time
    _insert(3, "2026-06-23T08:00:00Z", "2026-06-23T08:00:00Z")   # oldest
    eids = [e["source_event_id"] for e in db.student_tail("s1", 10)]
    assert eids == [3, 2, 1]


def test_reset_clears_apted_score_cache():
    from app.runs import apted_similarity
    apted_similarity._distance_cache[("a", "b")] = 9
    workers.reset()
    assert apted_similarity._distance_cache == {}      # reset drops the memoized distances


def test_session_cutoff_hides_pre_session_events_on_rehydrate():
    for sid_eid, ts in [(1, "2026-06-23T08:00:00Z"), (2, "2026-06-23T12:00:00Z")]:
        db.insert_message_and_log({
            "raw_message": "{}", "event_time": db.db_to_dt(ts), "classCode": "C",
            "eventType": "runProject", "studentID": "s1", "project": "{}",
            "source_event_id": sid_eid})
    workers.set_session_cutoff(db.db_to_dt("2026-06-23T10:00:00Z"))
    w = workers.get_worker("s1")
    assert len(w.events) == 1            # only the post-cutoff event replayed
    assert w.last_event_id == 2
