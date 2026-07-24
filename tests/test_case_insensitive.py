"""Case-insensitive identity + switch recording, end to end through a worker."""
from app import db
from app.pipeline import workers


def _ev(sid, cls, n, etype="pageLoad"):
    return {"studentID": sid, "classCode": cls, "eventType": etype,
            "raw_message": "{}", "source_event_id": n, "event_time": db.now()}


def test_tracking_folds_casing():
    db.tracked_add("Cobra3")
    db.tracked_add("cobra3")          # same handle, different casing
    db.tracked_add("COBRA3")
    rows = db.tracked_list()
    assert len(rows) == 1
    assert rows[0]["studentID"] == "cobra3"   # canonical key


def test_lookups_are_case_insensitive():
    db.tracked_add("Cobra3")
    db.set_presence("COBRA3", False)          # different casing than tracked
    db.set_picked("cobra3", True)
    db.add_note("CoBrA3", "seen switching")
    row = db.tracked_list()[0]
    assert row["present"] is False and row["picked"] is True
    assert len(db.list_notes("cobra3")) == 1


def test_one_worker_per_handle_and_display_is_most_recent():
    w = workers.get_worker("cobra3")
    assert workers.get_worker("COBRA3") is w      # same worker object
    w.ingest(_ev("cobra3", "FPFVDH", 1))
    w.ingest(_ev("Cobra3", "FPFVDH", 2))          # casing flip
    w.recompute_and_write()
    states = db.list_student_states(["COBRA3"])    # queried with a third casing
    assert len(states) == 1
    assert states[0]["display_id"] == "Cobra3"     # most-recent casing wins


def test_casing_and_class_switches_are_recorded():
    w = workers.get_worker("cobra3")
    w.ingest(_ev("cobra3", "FPFVDH", 1))           # first event: no switch
    w.ingest(_ev("Cobra3", "FPFVDH", 2))           # casing switch
    w.ingest(_ev("Cobra3", "AFURRR", 3))           # class switch
    kinds = [(s["kind"], s["from_value"], s["to_value"]) for s in db.list_switches()]
    assert ("casing", "cobra3", "Cobra3") in kinds
    assert ("class", "FPFVDH", "AFURRR") in kinds
    assert all(s["studentID"] == "cobra3" for s in db.list_switches())   # keyed canonical


def test_switches_api(client):
    db.tracked_add("bear2")   # the switches feed is scoped to the workspace roster
    w = workers.get_worker("bear2")
    w.ingest(_ev("bear2", "FPFVDH", 1))
    w.ingest(_ev("bear2", "AFURRR", 2))            # class switch
    body = client.get("/api/switches/").json()
    assert body["unacked"] == 1
    sw = body["switches"][0]
    assert sw["kind"] == "class" and sw["to"] == "AFURRR"
    assert client.post("/api/switches/ack/", json={"id": sw["id"]}).json()["acknowledged"] == 1
    assert client.get("/api/switches/").json()["unacked"] == 0


# --- integration: the case-insensitivity has to hold across the ingest paths ---

def _norm(sid, cls, eid, etype="runProject", ts="2026-06-22T10:00:00Z"):
    return {"studentID": sid, "classCode": cls, "eventType": etype, "project": "{}",
            "raw_message": "{}", "source_event_id": eid, "event_time": db.db_to_dt(ts)}


def test_drain_folds_casing_against_the_tracked_set():
    """A roster keyed 'cobra3' must ingest a prod event spelled 'Cobra3'."""
    from app.pipeline import poller

    class Fake:
        def __init__(self, pages):
            self.pages = pages

        def page_by_time(self, date_from, limit, offset):
            i = offset // limit
            return self.pages[i] if i < len(self.pages) else []

    ev = {"id": 1, "studentID": "Cobra3", "classCode": "AFURRR", "eventType": "runProject",
          "project": "{}", "raw_message": "{}", "recieved_at": "2026-06-22T10:00:00Z"}
    new = poller.drain(Fake([[ev]]), poller.get_cursor(), limit=100, tracked={"cobra3"})
    assert new == 1
    assert db._query("SELECT 1 FROM vex_log WHERE source_event_id=1") != []


def test_tracked_remove_folds_casing():
    db.insert_message_and_log(_norm("Cobra3", "AFURRR", 1))       # raw casing in vex_log
    db.upsert_student_state("cobra3", {"classCode": "AFURRR", "run_count": 0, "event_count": 1,
                                       "runs": None, "episodes": None, "playground_prompt": None,
                                       "playground_time": None, "last_event_id": 1,
                                       "last_event_time": db.now(), "display_id": "Cobra3"})
    db.tracked_add("cobra3")
    db.tracked_remove("COBRA3")                                   # yet another casing
    assert db.tracked_list() == []
    assert db._query("SELECT 1 FROM vex_log WHERE lower(studentID)='cobra3'") == []
    assert db.list_student_states(["cobra3"]) == []


def test_switch_events_are_shared_and_survive_a_workspace_reset():
    # switch_event is part of the shared per-student mirror, so a per-workspace
    # reset (researcher data only) leaves it intact.
    db.record_switch("cobra3", "class", "FPFVDH", "AFURRR")
    assert db.list_switches()
    db.reset_workspace()
    assert db.list_switches()


def test_rehydrate_reads_mixed_casing_and_lands_on_newest():
    db.insert_message_and_log(_norm("cobra3", "FPFVDH", 1, "pageLoad", "2026-06-22T10:00:00Z"))
    db.insert_message_and_log(_norm("Cobra3", "FPFVDH", 2, "runProject", "2026-06-22T10:05:00Z"))
    w = workers.get_worker("COBRA3")            # cold worker, canonical key -> rehydrates
    assert len(w.events) == 2                   # both spellings replayed via lower() match
    assert w.display_id == "Cobra3"             # newest casing survives a restart


# The one-time SQLite identity-fold migration that used to live in init_db is
# gone: on Postgres the schema starts fresh (the old db.sqlite3 was discarded, not
# migrated) and every studentID is written canonically via canon_id, so there is
# no pre-existing mixed-case data to fold. Live case-insensitivity is covered by
# the tests above.
