"""
The whole data layer, on top of the standard-library sqlite3 module (no ORM).

Everything about the database is concentrated here: the schema, the one shared
connection and its pragmas, and every read and write the API and pipeline make.
Keeping the SQL in a single module is deliberate, it's the seam that would let
a move to Postgres be a self-contained rewrite of this file.

Who writes what: the daemon owns all the derived state, while the API is mostly
a reader that also makes a few small writes (the tracked roster, acks, notes,
control flags). WAL mode plus a busy_timeout let the writer and the readers run
at the same time without blocking each other.

Datetime contract: rows are stored as UTC-naive strings in the fixed-width
format '%Y-%m-%d %H:%M:%S.%f', a legacy of the original Django writer. Because
the width is fixed, comparing the strings lexically is the same as comparing the
instants, which is what lets the cursor and cutoff SQL (ORDER BY started_at,
resolved_at >= cutoff) work directly on the stored text.
"""
import csv
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from app.config import DB_PATH

UTC = timezone.utc
_FMT = "%Y-%m-%d %H:%M:%S.%f"
_FMT_NOFRAC = "%Y-%m-%d %H:%M:%S"


# --------------------------------------------------------------------------
# value conversion
# --------------------------------------------------------------------------
def now():
    return datetime.now(UTC)


def dt_to_db(dt):
    """Serialize a datetime (aware or naive) into the UTC-naive string the DB
    stores. Returns None for None."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.strftime(_FMT)


def db_to_dt(s):
    """Parse a stored timestamp string back into an aware UTC datetime. Accepts
    the canonical format, the fraction-less variant, and ISO-8601 as a fallback;
    returns None when there's nothing parseable."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=UTC)
    s = s.strip()
    for fmt in (_FMT, _FMT_NOFRAC):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def _jload(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _jdump(o):
    return json.dumps(o) if o is not None else None


# --------------------------------------------------------------------------
# connection (one shared handle per process; sqlite3 forbids cross-thread use
# by default, so we opt out of that check)
# --------------------------------------------------------------------------
_con = None
_con_lock = threading.Lock()
# Guards multi-statement transactions. sqlite3 already serializes a single
# execute/fetchall with its own mutex, but a BEGIN..COMMIT spanning several
# statements is not atomic against other threads on the shared connection, so
# those transactions take this lock to stay atomic under FastAPI's threadpool.
_write_lock = threading.Lock()


def connect():
    """Return the process's single configured connection, creating it on first
    call. WAL is a file-level pragma that persists, so setting it once is enough;
    busy_timeout is per-connection but harmless to re-assert. The lock only
    guards the lazy initialization. check_same_thread=False lets the daemon's
    thread and FastAPI's worker threads share this one handle."""
    global _con
    if _con is not None:
        return _con
    with _con_lock:
        if _con is None:
            _con = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)
            _con.row_factory = sqlite3.Row
            _con.execute("PRAGMA journal_mode=WAL")
            _con.execute("PRAGMA synchronous=NORMAL")
            _con.execute("PRAGMA busy_timeout=5000")
    return _con


def _query(sql, params=()):
    return connect().execute(sql, params).fetchall()


def _execute(sql, params=()):
    """Run one self-contained write and commit it; returns the affected
    rowcount. Safe to call from multiple threads because a single statement on
    the shared connection is serialized by SQLite's own mutex."""
    con = connect()
    cur = con.execute(sql, params)
    con.commit()
    return cur.rowcount


class _WriteTxn:
    """A context manager for a multi-statement transaction on the shared
    connection. It holds _write_lock for the duration so the BEGIN..COMMIT stays
    atomic against other worker threads, commits on a clean exit, and rolls back
    if the block raises. Use it as `with db.write_txn() as con:`."""

    def __enter__(self):
        _write_lock.acquire()
        self.con = connect()
        self.con.execute("BEGIN")
        return self.con

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.con.commit()
            else:
                self.con.rollback()
        finally:
            _write_lock.release()
        return False


def write_txn():
    return _WriteTxn()


# --------------------------------------------------------------------------
# schema. Every statement is CREATE ... IF NOT EXISTS, so this is safe to run
# on every startup: it builds the tables on a fresh DB and is a no-op on one
# that already has them.
# --------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_name VARCHAR(255) NOT NULL,
    routing_key VARCHAR(255) NOT NULL DEFAULT '',
    exchange VARCHAR(255) NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    received_at DATETIME NOT NULL
);
CREATE TABLE IF NOT EXISTS vex_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_message_id BIGINT NOT NULL REFERENCES message(id),
    classCode TEXT, eventType TEXT, studentID TEXT, project TEXT,
    raw_message TEXT, event_time DATETIME,
    source_event_id BIGINT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_vex_student ON vex_log(studentID, id);
CREATE INDEX IF NOT EXISTS ix_vex_event_time ON vex_log(event_time);
CREATE TABLE IF NOT EXISTS ingest_cursor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) NOT NULL UNIQUE,
    last_source_id BIGINT NOT NULL DEFAULT 0,
    last_event_time DATETIME,
    updated_at DATETIME NOT NULL
);
CREATE TABLE IF NOT EXISTS student_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL UNIQUE,
    classCode VARCHAR(64),
    current_state INTEGER, state_label VARCHAR(32),
    stuck BOOL NOT NULL DEFAULT 0, consecutive_stuck INTEGER NOT NULL DEFAULT 0,
    run_count INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
    runs TEXT, episodes TEXT,
    playground_prompt TEXT, playground_time DATETIME,
    last_event_id BIGINT NOT NULL DEFAULT 0, last_event_time DATETIME,
    updated_at DATETIME NOT NULL
);
CREATE TABLE IF NOT EXISTS tracked_student (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL UNIQUE,
    backfilled BOOL NOT NULL DEFAULT 0,
    present BOOL NOT NULL DEFAULT 1,
    picked BOOL NOT NULL DEFAULT 0,
    picked_at DATETIME,
    created_at DATETIME NOT NULL
);
CREATE TABLE IF NOT EXISTS trigger_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL,
    trigger_type VARCHAR(24) NOT NULL,
    started_at DATETIME NOT NULL, last_seen_at DATETIME NOT NULL,
    resolved_at DATETIME, acknowledged BOOL NOT NULL DEFAULT 0,
    detail TEXT, created_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trig_student ON trigger_event(studentID, trigger_type);
CREATE INDEX IF NOT EXISTS ix_trig_resolved ON trigger_event(resolved_at);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL,
    ts DATETIME NOT NULL,
    text TEXT NOT NULL,
    trigger_id INTEGER,
    trigger_type VARCHAR(24),
    created_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_note_student ON note(studentID, ts);
CREATE TABLE IF NOT EXISTS pick_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL,
    picked BOOL NOT NULL,
    ts DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pick_student ON pick_event(studentID, ts);
"""


def init_db():
    with write_txn() as con:
        con.executescript(_SCHEMA)
        # Lightweight in-place migration: add the presence/picked columns if an
        # older database predates them. Guarded by a column check so it's
        # idempotent and needs no separate migration step.
        cols = {r[1] for r in con.execute("PRAGMA table_info(tracked_student)")}
        if "present" not in cols:
            con.execute("ALTER TABLE tracked_student ADD COLUMN present BOOL NOT NULL DEFAULT 1")
        if "picked" not in cols:
            con.execute("ALTER TABLE tracked_student ADD COLUMN picked BOOL NOT NULL DEFAULT 0")
        if "picked_at" not in cols:
            con.execute("ALTER TABLE tracked_student ADD COLUMN picked_at DATETIME")


# --------------------------------------------------------------------------
# meta: a tiny key/value store the two processes use to signal each other
# (the reset trigger, the polling pause flag, the disabled-trigger list)
# --------------------------------------------------------------------------
def set_meta(key, value):
    _execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    _meta_cache.pop(key, None)


def get_meta(key):
    rows = _query("SELECT value FROM meta WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


# In-process cache for the control flags. polling_enabled, reset_requested_at,
# and disabled_triggers only change when a human clicks something, yet the
# daemon would otherwise re-read them every tick. The 200ms TTL keeps a UI
# action visible almost immediately while collapsing those repeated reads; a
# local set_meta drops the entry so a write is never masked by a stale cache.
_meta_ttl_s = 0.2
_meta_cache = {}  # key -> (value, expires_at)
_meta_lock = threading.Lock()


def get_meta_cached(key):
    now_t = time.monotonic()
    cached = _meta_cache.get(key)
    if cached is not None and cached[1] > now_t:
        return cached[0]
    with _meta_lock:
        cached = _meta_cache.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        value = get_meta(key)
        _meta_cache[key] = (value, time.monotonic() + _meta_ttl_s)
        return value


def get_meta_many(keys):
    """Fetch several control flags at once. Serves whatever is still within its
    TTL from the cache and reads only the rest in a single query, so a tick that
    wants all three flags costs at most one round-trip."""
    out = {}
    missing = []
    now_t = time.monotonic()
    for k in keys:
        c = _meta_cache.get(k)
        if c is not None and c[1] > now_t:
            out[k] = c[0]
        else:
            missing.append(k)
    if missing:
        with _meta_lock:
            # re-check after lock (another thread may have filled it)
            now_t = time.monotonic()
            still_missing = []
            for k in missing:
                c = _meta_cache.get(k)
                if c is not None and c[1] > now_t:
                    out[k] = c[0]
                else:
                    still_missing.append(k)
            if still_missing:
                placeholders = ",".join("?" * len(still_missing))
                rows = _query(f"SELECT key, value FROM meta WHERE key IN ({placeholders})",
                              tuple(still_missing))
                present = {r["key"]: r["value"] for r in rows}
                for k in still_missing:
                    value = present.get(k)
                    out[k] = value
                    _meta_cache[k] = (value, time.monotonic() + _meta_ttl_s)
    return out


def reset_all():
    """Clear the local mirror: raw events, derived state, and the researcher
    notes. Deliberately spared are the tracked roster, the ingest cursor, and
    meta, so the board keeps its students and rebuilds only from activity that
    arrives after the reset rather than re-pulling old events. The /api/reset/
    endpoint writes a CSV backup (notes included) before calling this."""
    with write_txn() as con:
        for t in ("trigger_event", "student_state", "vex_log", "message", "note"):
            con.execute(f"DELETE FROM {t}")


# --------------------------------------------------------------------------
# CSV export. Two callers share this: scripts/export_csv.py for an end-of-day
# dump, and the reset endpoint to snapshot everything before it wipes.
# --------------------------------------------------------------------------
# Tables excluded from the dump: SQLite's own internal tables, the cursor
# bookkeeping (ingest_cursor), the control flags (meta), and the raw envelope
# (message), whose only research-relevant field is content, already copied into
# vex_log.raw_message.

_EXPORT_SKIP = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4",
                "ingest_cursor", "meta", "message"}


def _tree_to_brackets(text):
    """Flatten the indented playground_prompt tree onto a single line so it fits
    in one CSV cell, using nested braces to keep the parent/child structure.
    The depth-0 section headers ([Active]/[Orphaned]) stay as bare inline labels;
    only blocks at depth >= 1 that actually have children get wrapped in { }.
    Indentation is one space per level (matches smart_delta_engine.build_tree)."""
    lines = [(len(l) - len(l.lstrip(" ")), l.strip())
             for l in text.split("\n") if l.strip()]
    parts, open_depths = [], []
    for i, (depth, label) in enumerate(lines):
        while open_depths and open_depths[-1] >= depth:
            parts.append("}")
            open_depths.pop()
        parts.append(label)
        next_depth = lines[i + 1][0] if i + 1 < len(lines) else -1
        if next_depth > depth and depth >= 1:
            parts.append("{")
            open_depths.append(depth)
    parts.extend("}" for _ in open_depths)
    return " ".join(parts)


def _csv_value(col, val):
    """Normalize one cell so it never spans multiple physical lines. The
    playground_prompt column is re-bracketed into one line; for everything else,
    any embedded newline is replaced with a space."""
    if not isinstance(val, str):
        return val
    if col == "playground_prompt":
        val = _tree_to_brackets(val)
    if "\n" in val or "\r" in val:
        val = val.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return val


def export_csv(out_dir, tables=None, db_path=None):
    """Write one CSV file per table into out_dir (created if missing). Purely a
    read of the database, nothing is modified. JSON columns come out as their
    raw JSON text. Returns (out_dir, {table: row_count})."""
    os.makedirs(out_dir, exist_ok=True)
    con = sqlite3.connect(db_path or DB_PATH)
    try:
        if tables is None:
            tables = [
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall() if r[0] not in _EXPORT_SKIP
            ]
        written = {}
        for t in tables:
            cur = con.execute(f'SELECT * FROM "{t}"')
            cols = [d[0] for d in cur.description]
            with open(os.path.join(out_dir, f"{t}.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                n = 0
                for row in cur:
                    w.writerow([_csv_value(cols[i], row[i]) for i in range(len(cols))])
                    n += 1
            written[t] = n
        return out_dir, written
    finally:
        con.close()


# --------------------------------------------------------------------------
# row shaping
# --------------------------------------------------------------------------
def _student_state_row(r):
    return {
        "studentID": r["studentID"],
        "classCode": r["classCode"],
        "current_state": r["current_state"],
        "state_label": r["state_label"],
        "stuck": bool(r["stuck"]),
        "consecutive_stuck": r["consecutive_stuck"],
        "run_count": r["run_count"],
        "event_count": r["event_count"],
        "runs": _jload(r["runs"]),
        "episodes": _jload(r["episodes"]),
        "playground_prompt": r["playground_prompt"],
        "playground_time": db_to_dt(r["playground_time"]),
        "last_event_id": r["last_event_id"],
        "last_event_time": db_to_dt(r["last_event_time"]),
        "updated_at": db_to_dt(r["updated_at"]),
    }


def _trigger_row(r):
    return {
        "id": r["id"],
        "studentID": r["studentID"],
        "trigger_type": r["trigger_type"],
        "started_at": db_to_dt(r["started_at"]),
        "last_seen_at": db_to_dt(r["last_seen_at"]),
        "resolved_at": db_to_dt(r["resolved_at"]),
        "acknowledged": bool(r["acknowledged"]),
        "detail": _jload(r["detail"]),
    }


# ==========================================================================
# Queries the API layer calls: reads of the materialized state plus the small
# writes it owns (roster, acks, presence/picked toggles, notes).
# ==========================================================================
def list_student_states(students=None, class_code=None):
    sql = "SELECT * FROM student_state"
    clauses, params = [], []
    if students:
        clauses.append(f"studentID IN ({','.join('?' * len(students))})")
        params += list(students)
    if class_code:
        clauses.append("classCode = ?")
        params.append(class_code)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return [_student_state_row(r) for r in _query(sql, params)]


def triggers_feed(cutoff, limit=100):
    """The intervention feed: unacknowledged triggers that are either still open
    or were resolved at/after `cutoff`, newest first."""
    rows = _query(
        "SELECT * FROM trigger_event "
        "WHERE acknowledged = 0 AND (resolved_at IS NULL OR resolved_at >= ?) "
        "ORDER BY started_at DESC LIMIT ?",
        (dt_to_db(cutoff), limit),
    )
    return [_trigger_row(r) for r in rows]


def ack_by_id(tid):
    return _execute("UPDATE trigger_event SET acknowledged = 1 WHERE id = ?", (tid,))


def ack_by_student(sid):
    return _execute(
        "UPDATE trigger_event SET acknowledged = 1 "
        "WHERE studentID = ? AND acknowledged = 0",
        (sid,),
    )


def tracked_list():
    # A single LEFT JOIN rather than a roster query followed by per-student
    # lookups: has_data is just whether a matching student_state row exists.
    # studentID is UNIQUE on both tables, so the join is strictly 1:1.
    rows = _query(
        "SELECT t.studentID, t.backfilled, t.present, t.picked, t.picked_at, "
        "       (s.studentID IS NOT NULL) AS has_data "
        "FROM tracked_student t "
        "LEFT JOIN student_state s ON s.studentID = t.studentID "
        "ORDER BY t.studentID"
    )
    return [
        {
            "studentID": r["studentID"],
            "backfilled": bool(r["backfilled"]),
            "has_data": bool(r["has_data"]),
            "present": bool(r["present"]),
            "picked": bool(r["picked"]),
            "picked_at": r["picked_at"],
        }
        for r in rows
    ]


def set_presence(sid, present):
    """Researcher toggle for whether the student is physically in the room."""
    _execute(
        "UPDATE tracked_student SET present = ? WHERE studentID = ?",
        (1 if present else 0, sid),
    )


def set_picked(sid, picked):
    """Researcher toggle for whether the student has been picked/interviewed this
    session. Marking stamps picked_at; unmarking clears it. Either way it also
    appends a pick_event row, so the full pick/unpick history is timestamped for
    later analysis (picked_at only holds the latest state; pick_event is the log)."""
    ts = dt_to_db(now())
    with write_txn() as con:
        con.execute(
            "UPDATE tracked_student SET picked = ?, picked_at = ? WHERE studentID = ?",
            (1 if picked else 0, ts if picked else None, sid),
        )
        con.execute(
            "INSERT INTO pick_event (studentID, picked, ts) VALUES (?, ?, ?)",
            (sid, 1 if picked else 0, ts),
        )


def add_note(student_id, text, trigger_id=None, trigger_type=None):
    """Record one note for a student. Pass trigger_id/trigger_type to link it to
    the alert it was written from; leave both None for a free-standing manual
    note. Returns the new row as a dict."""
    ts = dt_to_db(now())
    with write_txn() as con:
        cur = con.execute(
            "INSERT INTO note (studentID, ts, text, trigger_id, trigger_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, ts, text, trigger_id, trigger_type, ts),
        )
        nid = cur.lastrowid
    return {
        "id": nid, "studentID": student_id, "ts": ts, "text": text,
        "trigger_id": trigger_id, "trigger_type": trigger_type, "created_at": ts,
    }


def list_notes(student_id):
    """Every note for a student, in chronological order."""
    rows = _query(
        "SELECT id, studentID, ts, text, trigger_id, trigger_type, created_at "
        "FROM note WHERE studentID = ? ORDER BY ts, id",
        (student_id,),
    )
    return [dict(r) for r in rows]


def tracked_add(sid):
    """Add a student to the roster (no-op if already there). The daemon notices
    the new, not-yet-backfilled row on its next tick and pulls their history."""
    _execute(
        "INSERT OR IGNORE INTO tracked_student (studentID, backfilled, created_at) "
        "VALUES (?, 0, ?)",
        (sid, dt_to_db(now())),
    )


def mark_backfilled(sid):
    _execute("UPDATE tracked_student SET backfilled = 1 WHERE studentID = ?", (sid,))


def tracked_remove(sid):
    """Untrack a student and delete everything tied to them, raw events and
    derived state alike, so they disappear from the board entirely."""
    with write_txn() as con:
        msg_ids = [
            row[0]
            for row in con.execute(
                "SELECT from_message_id FROM vex_log WHERE studentID = ?", (sid,)
            ).fetchall()
        ]
        con.execute("DELETE FROM vex_log WHERE studentID = ?", (sid,))
        if msg_ids:
            con.executemany(
                "DELETE FROM message WHERE id = ?", [(m,) for m in msg_ids]
            )
        con.execute("DELETE FROM student_state WHERE studentID = ?", (sid,))
        con.execute("DELETE FROM trigger_event WHERE studentID = ?", (sid,))
        con.execute("DELETE FROM tracked_student WHERE studentID = ?", (sid,))


# ==========================================================================
# Pipeline queries: the ingest cursor (how far the poller has consumed)
# ==========================================================================
def get_or_create_cursor(name):
    rows = _query("SELECT * FROM ingest_cursor WHERE name = ?", (name,))
    if not rows:
        _execute(
            "INSERT INTO ingest_cursor (name, last_source_id, last_event_time, updated_at) "
            "VALUES (?, 0, NULL, ?)",
            (name, dt_to_db(now())),
        )
        rows = _query("SELECT * FROM ingest_cursor WHERE name = ?", (name,))
    r = rows[0]
    return {
        "name": r["name"],
        "last_source_id": r["last_source_id"] or 0,
        "last_event_time": db_to_dt(r["last_event_time"]),
    }


def save_cursor(name, last_event_time, last_source_id):
    _execute(
        "UPDATE ingest_cursor SET last_event_time = ?, last_source_id = ?, updated_at = ? "
        "WHERE name = ?",
        (dt_to_db(last_event_time), last_source_id, dt_to_db(now()), name),
    )


# ==========================================================================
# Pipeline queries: the append-only raw event log (written only by the poller)
# ==========================================================================
def log_exists(source_event_id):
    if source_event_id is None:
        return False
    return bool(
        _query("SELECT 1 FROM vex_log WHERE source_event_id = ? LIMIT 1", (source_event_id,))
    )


def insert_message_and_log(norm):
    """Insert one event, envelope row plus parsed log row, in a single
    transaction. Idempotent: returns True on insert, False when the UNIQUE
    source_event_id already exists (a duplicate or a race). Callers normally
    skip the write via log_exists() first; the IntegrityError catch here is the
    backstop for the rare concurrent duplicate."""
    try:
        with write_txn() as con:
            cur = con.execute(
                "INSERT INTO message (queue_name, routing_key, exchange, content, received_at) "
                "VALUES ('pipeline', '', '', ?, ?)",
                (norm["raw_message"], dt_to_db(norm["event_time"] or now())),
            )
            con.execute(
                "INSERT INTO vex_log "
                "(from_message_id, classCode, eventType, studentID, project, raw_message, "
                " event_time, source_event_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cur.lastrowid,
                    norm["classCode"],
                    norm["eventType"],
                    norm["studentID"],
                    norm["project"],
                    norm["raw_message"],
                    dt_to_db(norm["event_time"]),
                    norm["source_event_id"],
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def student_tail(sid, limit):
    """A student's last `limit` events, returned oldest-first so a worker can
    replay them in order on rehydrate. Joins in the envelope's received_at to use
    as a timestamp fallback when the parsed event_time is missing."""
    rows = _query(
        "SELECT v.eventType, v.classCode, v.project, v.raw_message, v.event_time, "
        "       v.source_event_id, m.received_at "
        "FROM vex_log v LEFT JOIN message m ON m.id = v.from_message_id "
        "WHERE v.studentID = ? ORDER BY v.id DESC LIMIT ?",
        (sid, limit),
    )
    out = []
    for r in reversed(rows):
        out.append(
            {
                "eventType": r["eventType"],
                "classCode": r["classCode"],
                "project": r["project"],
                "raw_message": r["raw_message"],
                "event_time": db_to_dt(r["event_time"]),
                "received_at": db_to_dt(r["received_at"]),
                "source_event_id": r["source_event_id"],
            }
        )
    return out


# ==========================================================================
# Pipeline queries: the materialized student_state view (daemon writes it,
# the API reads it)
# ==========================================================================
_STATE_DT_FIELDS = ("playground_time", "last_event_time")
_STATE_JSON_FIELDS = ("runs", "episodes")


def upsert_student_state(student_id, defaults):
    cols = {"studentID": student_id, "updated_at": dt_to_db(now())}
    for k, v in defaults.items():
        if k in _STATE_JSON_FIELDS:
            v = _jdump(v)
        elif k in _STATE_DT_FIELDS:
            v = dt_to_db(v)
        elif isinstance(v, bool):
            v = int(v)
        cols[k] = v
    keys = list(cols.keys())
    updates = ", ".join(f"{k}=excluded.{k}" for k in keys if k != "studentID")
    sql = (
        f"INSERT INTO student_state ({', '.join(keys)}) "
        f"VALUES ({', '.join('?' * len(keys))}) "
        f"ON CONFLICT(studentID) DO UPDATE SET {updates}"
    )
    _execute(sql, tuple(cols[k] for k in keys))


# ==========================================================================
# Pipeline queries: trigger_event lifecycle (open / touch / resolve)
# ==========================================================================
def all_student_states():
    """A trimmed projection of every student_state row, just the columns the
    trigger evaluator needs to sweep over."""
    rows = _query(
        "SELECT studentID, current_state, consecutive_stuck, last_event_time, runs "
        "FROM student_state"
    )
    return [
        {
            "studentID": r["studentID"],
            "current_state": r["current_state"],
            "consecutive_stuck": r["consecutive_stuck"],
            "last_event_time": db_to_dt(r["last_event_time"]),
            "runs": _jload(r["runs"]),
        }
        for r in rows
    ]


def current_open_trigger(student_id, ttype):
    rows = _query(
        "SELECT * FROM trigger_event "
        "WHERE studentID = ? AND trigger_type = ? AND resolved_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1",
        (student_id, ttype),
    )
    return _trigger_row(rows[0]) if rows else None


def create_trigger(student_id, trigger_type, started_at, last_seen_at, resolved_at, detail):
    _execute(
        "INSERT INTO trigger_event "
        "(studentID, trigger_type, started_at, last_seen_at, resolved_at, "
        " acknowledged, detail, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        (
            student_id,
            trigger_type,
            dt_to_db(started_at),
            dt_to_db(last_seen_at),
            dt_to_db(resolved_at),
            _jdump(detail),
            dt_to_db(now()),
        ),
    )


def touch_trigger(trigger_id, last_seen_at, detail):
    _execute(
        "UPDATE trigger_event SET last_seen_at = ?, detail = ? WHERE id = ?",
        (dt_to_db(last_seen_at), _jdump(detail), trigger_id),
    )


def resolve_trigger(trigger_id, resolved_at):
    _execute(
        "UPDATE trigger_event SET resolved_at = ? WHERE id = ?",
        (dt_to_db(resolved_at), trigger_id),
    )


def big_change_indices(student_id):
    """The set of run indices that have already produced a big_change alert. A
    worker loads this once on cold start to seed its in-memory dedupe, so a
    restart never re-fires an old run, and the per-tick trigger sweep doesn't
    have to re-scan history to figure that out."""
    rows = _query(
        "SELECT json_extract(detail, '$.run_index') AS i FROM trigger_event "
        "WHERE studentID = ? AND trigger_type = 'big_change'",
        (student_id,),
    )
    return {r["i"] for r in rows if r["i"] is not None}
