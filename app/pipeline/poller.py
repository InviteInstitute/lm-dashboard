"""
Ingestion poller: the single writer to raw logs.

Bulk poll prod (timestamp cursor via dateFrom, with overlap), persist each
event idempotently (UNIQUE source_event_id), route to the student's worker, and
advance the cursor only after a full drain is durably written (persist-then-
advance). A crash mid-drain re-fetches the overlap window; idempotency dedupes.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from app import db
from app.pipeline.workers import route

logger = logging.getLogger("pipeline")

CURSOR_NAME = "vex_poll"


class Cursor:
    """Mutable in-memory view of the persisted ingest cursor."""

    def __init__(self, name, last_source_id, last_event_time):
        self.name = name
        self.last_source_id = last_source_id
        self.last_event_time = last_event_time

    def save(self):
        db.save_cursor(self.name, self.last_event_time, self.last_source_id)


def get_cursor():
    c = db.get_or_create_cursor(CURSOR_NAME)
    return Cursor(c["name"], c["last_source_id"], c["last_event_time"])


def get_cursor_lag(cursor):
    """How far behind the last persisted event we are."""
    if not cursor.last_event_time:
        return "n/a"
    secs = (db.now() - cursor.last_event_time).total_seconds()
    return f"{secs:.1f}s"


def _parse_ts(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _event_ts_raw(ev):
    """Prod's serializer historically had a typo ('recieved_at'); accept the
    correctly-spelled key too so a future fix doesn't silently stop advancing
    the cursor."""
    return ev.get("recieved_at") or ev.get("received_at")


def _normalize(ev):
    return {
        "studentID": ev.get("studentID") or "",
        "classCode": ev.get("classCode") or "",
        "eventType": ev.get("eventType") or "",
        "project": ev.get("project") or "",
        "raw_message": ev.get("raw_message", "{}"),
        "source_event_id": ev.get("id"),
        "event_time": _parse_ts(_event_ts_raw(ev)),
    }


def persist(ev):
    """Idempotent insert. Returns (inserted: bool, normalized: dict)."""
    norm = _normalize(ev)
    src_id = norm["source_event_id"]
    if src_id is not None and db.log_exists(src_id):
        return False, norm
    inserted = db.insert_message_and_log(norm)  # False if UNIQUE raced
    return inserted, norm


def drain(client, cursor, limit=500, overlap_seconds=2, tracked=None):
    """Page until caught up. Persist + route only events for `tracked` students
    (None = all). The cursor still advances over EVERY event so we stay caught
    up on the full stream even while ingesting a subset."""
    date_from = None
    if cursor.last_event_time:
        date_from = (cursor.last_event_time - timedelta(seconds=overlap_seconds)).isoformat()

    offset, new_count = 0, 0
    max_et = cursor.last_event_time
    max_id = cursor.last_source_id or 0

    while True:
        results = client.page_by_time(date_from, limit, offset)
        if not results:
            break
        for ev in results:
            et = _parse_ts(_event_ts_raw(ev))
            sid = ev.get("id")
            if et and (max_et is None or et > max_et):
                max_et = et
            if sid and sid > max_id:
                max_id = sid
            if tracked is not None and (ev.get("studentID") or "") not in tracked:
                continue
            inserted, norm = persist(ev)
            if inserted:
                try:
                    route(norm)
                    new_count += 1
                except Exception:
                    # The event landed in vex_log but we failed to push it
                    # into the in-memory worker. Drop the worker so the next
                    # tick rehydrates from the DB (which now includes this
                    # event) instead of serving a buffer that's missing it.
                    from app.pipeline import workers
                    workers._workers.pop(norm["studentID"], None)
                    logger.exception(
                        "route failed for %s after persist; dropped worker for rehydrate",
                        norm["studentID"],
                    )
                    raise
        if len(results) < limit:
            break
        offset += limit

    # caught up -> persist-then-advance
    if max_et != cursor.last_event_time or max_id != (cursor.last_source_id or 0):
        cursor.last_event_time = max_et
        cursor.last_source_id = max_id
        cursor.save()
    return new_count


def backfill_student(client, student_id, max_events=600, page_size=200):
    """Pull a newly-tracked student's recent history (idempotent) so their
    state materializes immediately on add."""
    inserted = 0
    for offset in range(0, max_events, page_size):
        results = client.page_student(student_id, page_size, offset)
        if not results:
            break
        page_new = 0
        for ev in results:
            was_in, norm = persist(ev)
            if was_in:
                route(norm)
                inserted += 1
                page_new += 1
        if len(results) < page_size or page_new == 0:
            break
    return inserted
