"""The daemon's ZANY source (app/zany.py): new study rows from ATLAS's log store, and backfill for
a newly tracked ZANY student. Like the Reflecks poller, it polls every tick, stores a row before
routing it to the student's worker, and keeps a cursor: the newest stored_at seen in the tracked
students' studies."""

import logging
from datetime import UTC, datetime, timedelta

import psycopg

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


# As Reflecks' drain re-reads an overlap (poller.drain's overlap_seconds), each drain reads again
# the rows stored in the last OVERLAP before the newest it has seen: ATLAS stamps a row before its
# transaction commits, so a row can turn up after a newer one. Rows already stored are skipped.
# ponytail: a row whose transaction takes longer than OVERLAP to commit is missed until the daemon
# restarts (which rebuilds every ZANY student); ATLAS's insert is one statement, so only a stuck
# store does that. Number the rows by commit (xid8 column) if that is ever not enough.
OVERLAP = timedelta(seconds=5)

_con = None


def _store():
    """One connection to the store, kept across ticks; a new one after it failed."""
    global _con
    if _con is None or _con.closed or _con.broken:
        _con = zany.connect()
    return _con


def drain(cursor, tracked, since=None):
    """Store and route every row of a tracked ZANY student stored since the cursor (less OVERLAP)
    and at or after `since` (the daemon's session cutoff). Returns how many were new."""
    studies = {zany.split(sid)[0].upper() for sid in tracked if zany.is_zany(sid)}
    if not studies:
        return 0
    # ATLAS names studies STUDY-0001; a tracked ID is case-folded (db.canon_id).
    starts = [t for t in (since, cursor.last_event_time and cursor.last_event_time - OVERLAP) if t]
    start = max(starts, default=datetime.min.replace(tzinfo=UTC))
    seen = (cursor.last_event_time, cursor.last_source_id)
    new, after = 0, None
    con = _store()
    try:
        while True:
            rows = zany.rows_since(con, studies, start, after)
            for seq, study, stored_at, record in rows:
                after = (stored_at, seq)
                if cursor.last_event_time is None or stored_at > cursor.last_event_time:
                    cursor.last_event_time = stored_at
                cursor.last_source_id = max(cursor.last_source_id or 0, seq)
                norm = zany._event(seq, study, stored_at, record)
                if db.canon_id(norm["studentID"]) not in tracked or not _persist(norm):
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
    except psycopg.Error:
        con.close()  # the next tick connects again
        raise
    if (cursor.last_event_time, cursor.last_source_id) != seen:
        cursor.save()
    return new


def backfill_student(student_id, since=None):
    """Store a newly tracked ZANY student's rows (oldest first, from `since`). The caller rebuilds
    their worker from the log. Returns how many were new."""
    with zany.connect() as con:
        rows = zany.student_rows(con, student_id, since)
    return sum(_persist(zany._event(*row)) for row in rows)
