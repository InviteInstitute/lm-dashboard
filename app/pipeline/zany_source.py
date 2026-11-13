"""The daemon's ZANY source (app/zany.py): new study rows from ATLAS's log store, and backfill for
a newly tracked ZANY student. Like the Reflecks poller, it stores a row before routing it to the
student's worker, and a cursor (the last store seq seen) passes every row, tracked or not."""

import logging

from app import db, zany
from app.pipeline import poller, workers

log = logging.getLogger("pipeline")

CURSOR = "zany"


def get_cursor():
    c = db.get_or_create_cursor(CURSOR)
    return poller.Cursor(c["name"], c["last_source_id"], c["last_event_time"])


def _persist(norm):
    """Store one ZANY event unless its store row is already in; True when it was stored."""
    if db.zany_row_exists(norm["zany_seq"]):
        return False
    return db.insert_message_and_log(norm)


def drain(cursor, tracked, since=None):
    """Store and route every row after the cursor that belongs to a tracked ZANY student and was
    stored at or after `since` (the daemon's session cutoff). Returns how many were new."""
    new = 0
    with zany.connect() as con:
        while True:
            rows = zany.rows_after(con, cursor.last_source_id or 0)
            for seq, study, stored_at, record in rows:
                cursor.last_source_id = seq
                cursor.last_event_time = stored_at
                norm = zany._event(seq, study, stored_at, record)
                if db.canon_id(norm["studentID"]) not in tracked:
                    continue
                if since is not None and stored_at < since:
                    continue
                if not _persist(norm):
                    continue
                try:
                    workers.route(norm)
                except Exception:
                    # Stored but not routed: drop the worker so it rebuilds from the log.
                    workers._workers.pop(db.canon_id(norm["studentID"]), None)
                    raise
                new += 1
            if len(rows) < zany.PAGE:
                break
    cursor.save()
    return new


def backfill_student(student_id, since=None):
    """Store a newly tracked ZANY student's rows (oldest first, from `since`). The caller rebuilds
    their worker from the log. Returns how many were new."""
    with zany.connect() as con:
        rows = zany.student_rows(con, student_id, since)
    return sum(_persist(zany._event(*row)) for row in rows)
