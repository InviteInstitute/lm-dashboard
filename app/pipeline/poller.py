"""
The ingestion poller: the half of the daemon that fills the raw event log.

It bulk-pages prod using a timestamp cursor (the `dateFrom` filter, with a small
overlap window), persists each event idempotently against a UNIQUE
source_event_id, routes the new ones to the right student's worker, and only
advances the cursor once a full drain is safely written, persist first, then
advance. That ordering is what makes a crash mid-drain harmless: on restart it
re-fetches the overlap window and idempotency throws away the duplicates.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from app import db
from app.pipeline.workers import route

logger = logging.getLogger("pipeline")

CURSOR_NAME = "vex_poll"


class Cursor:
    """A mutable in-memory copy of the persisted ingest cursor. Mutate its
    fields during a drain, then call save() to write them back."""

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
    """How far behind real time the last persisted event is, as a display
    string. Returns "n/a" before the cursor has seen anything."""
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
    """Read an event's received timestamp, tolerating the historical misspelling.
    Prod's serializer shipped the key as 'recieved_at'; we check the correct
    'received_at' too so the cursor keeps advancing if prod ever fixes it."""
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
    """Normalize a raw prod event and insert it idempotently. Skips the write if
    we've already stored that source_event_id. Returns (inserted, normalized)
    where inserted is False for a duplicate."""
    norm = _normalize(ev)
    src_id = norm["source_event_id"]
    if src_id is not None and db.log_exists(src_id):
        return False, norm
    inserted = db.insert_message_and_log(norm)  # False if UNIQUE raced
    return inserted, norm


def drain(client, cursor, limit=500, overlap_seconds=2, tracked=None, since=None):
    """Page through prod until caught up. Only events for `tracked` students are
    persisted and routed (None means all of them), but the cursor still advances
    past EVERY event seen, so ingesting a subset never leaves us perpetually
    behind on the full stream. `since` (a UTC datetime, or None) is the session
    cutoff: events older than it are skipped (not persisted) so a returning
    student's earlier sessions don't leak in -- the cursor still advances past
    them. Returns the number of newly-inserted events."""
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
            if since is not None and et is not None and et < since:
                continue   # before the session cutoff -- skip, but the cursor still advanced above
            inserted, norm = persist(ev)
            if inserted:
                try:
                    route(norm)
                    new_count += 1
                except Exception:
                    # The row is already in vex_log, but routing it into the
                    # in-memory worker failed. Discard that worker so the next
                    # tick rebuilds it from the DB (which now has this event),
                    # rather than keep serving a buffer that's silently missing it.
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

    # Drain finished and everything is durably written, now advance the cursor.
    if max_et != cursor.last_event_time or max_id != (cursor.last_source_id or 0):
        cursor.last_event_time = max_et
        cursor.last_source_id = max_id
        cursor.save()
    return new_count


def backfill_student(client, student_id, since=None, max_events=600, page_size=200):
    """Pull a newly-tracked student's recent history idempotently so their state
    materializes the moment they're added, rather than waiting for live activity.
    Separate from the cursor. `since` (a UTC datetime, or None) is the session
    cutoff: page_student returns newest-first, so once we pass an event older than
    `since` every remaining one is older too and we stop -- this is what keeps a
    returning student's earlier sessions from leaking in. Without a cutoff it
    falls back to the last `max_events`. Returns the number of events inserted."""
    inserted = 0
    for offset in range(0, max_events, page_size):
        results = client.page_student(student_id, page_size, offset)
        if not results:
            break
        page_new, stop = 0, False
        for ev in results:
            if since is not None:
                et = _parse_ts(_event_ts_raw(ev))
                if et is not None and et < since:   # newest-first: the rest are older too
                    stop = True
                    break
            was_in, norm = persist(ev)
            if was_in:
                route(norm)
                inserted += 1
                page_new += 1
        if stop or len(results) < page_size or page_new == 0:
            break
    return inserted
