"""Ingestion poller: normalization (incl. the prod 'recieved_at' typo),
idempotent persist, cursor advance, the tracked-only filter, and backfill."""
from app import db
from app.pipeline import poller, workers


class FakeClient:
    """Serves preloaded pages; records the params it was asked for."""
    def __init__(self, time_pages=None, student_pages=None):
        self.time_pages = time_pages or []
        self.student_pages = student_pages or []
        self.time_calls = []

    def page_by_time(self, date_from, limit, offset):
        self.time_calls.append((date_from, limit, offset))
        idx = offset // limit
        return self.time_pages[idx] if idx < len(self.time_pages) else []

    def page_student(self, sid, limit, offset):
        idx = offset // limit
        return self.student_pages[idx] if idx < len(self.student_pages) else []


def _ev(eid, sid, et="runProject", ts="2026-06-22T10:00:00Z", typo=True):
    e = {"id": eid, "studentID": sid, "classCode": "C1", "eventType": et,
         "project": "{}", "raw_message": "{}"}
    e["recieved_at" if typo else "received_at"] = ts
    return e


def test_normalize_handles_prod_typo_and_correct_key():
    n1 = poller._normalize(_ev(1, "s1", typo=True))
    n2 = poller._normalize(_ev(2, "s1", typo=False))
    assert n1["event_time"] is not None and n2["event_time"] is not None
    assert n1["studentID"] == "s1" and n1["source_event_id"] == 1


def test_parse_ts_variants():
    assert poller._parse_ts("2026-06-22T10:00:00Z").year == 2026
    assert poller._parse_ts("2026-06-22T10:00:00+00:00").hour == 10
    assert poller._parse_ts(None) is None
    assert poller._parse_ts("garbage") is None


def test_persist_is_idempotent_on_source_event_id():
    ev = _ev(42, "s1")
    inserted1, _ = poller.persist(ev)
    inserted2, _ = poller.persist(ev)
    assert inserted1 is True and inserted2 is False
    assert len(db._query("SELECT 1 FROM vex_log WHERE source_event_id=42")) == 1


def test_drain_persists_only_tracked_but_advances_cursor_over_all():
    cursor = poller.get_cursor()
    client = FakeClient(time_pages=[[
        _ev(1, "tracked", ts="2026-06-22T10:00:00Z"),
        _ev(2, "stranger", ts="2026-06-22T10:05:00Z"),   # newer, NOT tracked
    ]])
    new = poller.drain(client, cursor, limit=100, tracked={"tracked"})
    assert new == 1                                       # only the tracked one persisted
    assert db._query("SELECT 1 FROM vex_log WHERE studentID='stranger'") == []
    # cursor advanced over EVERY event, including the untracked newest one
    assert cursor.last_source_id == 2
    assert cursor.last_event_time.minute == 5


def test_drain_pages_until_short_page():
    cursor = poller.get_cursor()
    page1 = [_ev(i, "s1", ts=f"2026-06-22T10:00:0{i}Z") for i in range(1, 6)]  # full page of 5
    page2 = [_ev(6, "s1", ts="2026-06-22T10:01:00Z")]                          # short -> stop
    client = FakeClient(time_pages=[page1, page2])
    poller.drain(client, cursor, limit=5, tracked={"s1"})
    assert len(db._query("SELECT 1 FROM vex_log WHERE studentID='s1'")) == 6
    assert [c[2] for c in client.time_calls] == [0, 5]    # offsets requested


def test_backfill_student_persists_and_stops_on_short_page():
    client = FakeClient(student_pages=[[_ev(10, "s1"), _ev(11, "s1")]])
    inserted = poller.backfill_student(client, "s1", max_events=600, page_size=200)
    assert inserted == 2
    assert len(db._query("SELECT 1 FROM vex_log WHERE studentID='s1'")) == 2


def test_backfill_stops_when_page_is_all_duplicates(monkeypatch):
    db.insert_message_and_log(poller._normalize(_ev(10, "s1")))   # pre-existing
    client = FakeClient(student_pages=[[_ev(10, "s1")]])          # same event again
    inserted = poller.backfill_student(client, "s1", max_events=600, page_size=200)
    assert inserted == 0                                          # nothing new -> stop


def test_backfill_breaks_on_empty_page():
    inserted = poller.backfill_student(FakeClient(student_pages=[[]]), "s1")
    assert inserted == 0                                          # empty first page -> stop


def test_backfill_respects_since_cutoff():
    """page_student is newest-first, so backfill stops at the first event older
    than the cutoff and persists only the session's events."""
    since = db.db_to_dt("2026-06-23T10:00:00Z")
    client = FakeClient(student_pages=[[
        _ev(3, "s1", ts="2026-06-23T12:00:00Z"),   # after cutoff -> kept
        _ev(2, "s1", ts="2026-06-23T09:00:00Z"),   # before -> stop here
        _ev(1, "s1", ts="2026-06-22T12:00:00Z"),   # earlier session -> never reached
    ]])
    inserted = poller.backfill_student(client, "s1", since=since)
    assert inserted == 1
    assert [r["source_event_id"] for r in db._query(
        "SELECT source_event_id FROM vex_log")] == [3]


def test_drain_respects_since_cutoff():
    since = db.db_to_dt("2026-06-23T10:00:00Z")
    cursor = poller.get_cursor()
    client = FakeClient(time_pages=[[
        _ev(1, "s1", ts="2026-06-23T08:00:00Z"),   # before cutoff -> skipped
        _ev(2, "s1", ts="2026-06-23T11:00:00Z"),   # after -> kept
    ]])
    new = poller.drain(client, cursor, limit=100, tracked={"s1"}, since=since)
    assert new == 1
    assert [r["source_event_id"] for r in db._query(
        "SELECT source_event_id FROM vex_log")] == [2]
    assert cursor.last_source_id == 2                 # cursor still advanced over both


def test_drain_drops_worker_and_reraises_when_route_fails(monkeypatch):
    def boom(_norm):
        raise RuntimeError("route exploded")
    monkeypatch.setattr(poller, "route", boom)
    workers.get_worker("s1")                                      # cache a worker first
    cursor = poller.get_cursor()
    client = FakeClient(time_pages=[[_ev(1, "s1")]])
    import pytest
    with pytest.raises(RuntimeError):
        poller.drain(client, cursor, limit=100, tracked={"s1"})
    # the event still persisted; the worker was dropped so the next tick rehydrates
    assert db._query("SELECT 1 FROM vex_log WHERE source_event_id=1") != []
    assert not workers.has_worker("s1")
