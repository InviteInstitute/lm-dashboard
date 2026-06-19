"""
Raw-sqlite3 data layer. Replaces the old Django ORM/models.

One file owns the schema, the connection (WAL + the pragmas the old AppConfig
set), and every query the API and the pipeline need. Two processes share the
DB: the daemon is the only writer of derived state; the API reads it (+ writes
the tracked allowlist / acks). WAL + busy_timeout keep them from blocking.

Datetime contract: the existing rows were written by Django as UTC-naive
strings '%Y-%m-%d %H:%M:%S.%f'. We read/write that exact format so lexical
string comparison stays chronological (ORDER BY started_at, resolved_at >= cutoff).
"""
import csv
import json
import os
import sqlite3
from contextlib import closing
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
    """aware/naive datetime -> the UTC-naive string SQLite holds (or None)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.strftime(_FMT)


def db_to_dt(s):
    """stored string -> aware UTC datetime (or None)."""
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
# connection
# --------------------------------------------------------------------------
def connect():
    """A fresh, configured connection. Cheap; callers open per operation
    (sqlite3 connections aren't shareable across threads)."""
    con = sqlite3.connect(DB_PATH, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _query(sql, params=()):
    with closing(connect()) as con:
        return con.execute(sql, params).fetchall()


def _execute(sql, params=()):
    """Single write; returns affected rowcount."""
    with closing(connect()) as con:
        cur = con.execute(sql, params)
        con.commit()
        return cur.rowcount


# --------------------------------------------------------------------------
# schema (CREATE IF NOT EXISTS, so a fresh DB works and an existing one is left alone)
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
    with closing(connect()) as con:
        con.executescript(_SCHEMA)
        # Idempotent column adds so a DB created before the presence/picked
        # toggles existed picks them up without a manual migration.
        cols = {r[1] for r in con.execute("PRAGMA table_info(tracked_student)")}
        if "present" not in cols:
            con.execute("ALTER TABLE tracked_student ADD COLUMN present BOOL NOT NULL DEFAULT 1")
        if "picked" not in cols:
            con.execute("ALTER TABLE tracked_student ADD COLUMN picked BOOL NOT NULL DEFAULT 0")
        if "picked_at" not in cols:
            con.execute("ALTER TABLE tracked_student ADD COLUMN picked_at DATETIME")
        con.commit()


# --------------------------------------------------------------------------
# meta key/value (used for the cross-process reset signal)
# --------------------------------------------------------------------------
def set_meta(key, value):
    _execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(key):
    rows = _query("SELECT value FROM meta WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def reset_all():
    """Wipe the local mirror's raw + derived data AND the researcher notes (keeps
    the tracked roster, the ingest cursor, and meta). The reset endpoint saves a
    CSV backup first, so the notes are preserved before they are cleared here. The
    cursor is left in place so old events are NOT re-pulled."""
    with closing(connect()) as con:
        con.execute("BEGIN")
        try:
            for t in ("trigger_event", "student_state", "vex_log", "message", "note"):
                con.execute(f"DELETE FROM {t}")
            con.commit()
        except Exception:
            con.rollback()
            raise


# --------------------------------------------------------------------------
# CSV export (used by scripts/export_csv.py and by reset to back up first)
# --------------------------------------------------------------------------
# Tables left out of the CSV export: sqlite internals, pipeline bookkeeping
# (ingest_cursor), control flags (meta), and the raw envelope (message) whose
# only research field, content, is already duplicated in vex_log.raw_message.

_EXPORT_SKIP = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4",
                "ingest_cursor", "meta", "message"}


def _tree_to_brackets(text):
    """Collapse the indented playground_prompt tree into one line, showing
    parent->child with nested braces. Section headers ([Active]/[Orphaned], at
    depth 0) stay as plain inline labels; only blocks (depth >= 1) that have
    children get wrapped in { }. Indentation in the prompt is one space per
    depth level (see smart_delta_engine.build_tree)."""
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
    """Keep every CSV cell on a single physical line. The playground_prompt tree
    is rebracketed; any other stray newline becomes a space."""
    if not isinstance(val, str):
        return val
    if col == "playground_prompt":
        val = _tree_to_brackets(val)
    if "\n" in val or "\r" in val:
        val = val.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return val


def export_csv(out_dir, tables=None, db_path=None):
    """Dump tables to CSV (one file per table) into out_dir. Read-only.
    JSON columns are written as raw JSON text. Returns (out_dir, {table: rows})."""
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
# API reads / writes
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
    """Unacked triggers that are active OR resolved since `cutoff`, newest first."""
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
    have = {
        r["studentID"]
        for r in _query("SELECT studentID FROM student_state")
    }
    rows = _query(
        "SELECT studentID, backfilled, present, picked, picked_at "
        "FROM tracked_student ORDER BY studentID"
    )
    return [
        {
            "studentID": r["studentID"],
            "backfilled": bool(r["backfilled"]),
            "has_data": r["studentID"] in have,
            "present": bool(r["present"]),
            "picked": bool(r["picked"]),
            "picked_at": r["picked_at"],
        }
        for r in rows
    ]


def set_presence(sid, present):
    """Researcher toggle: is this student in the room right now."""
    _execute(
        "UPDATE tracked_student SET present = ? WHERE studentID = ?",
        (1 if present else 0, sid),
    )


def set_picked(sid, picked):
    """Researcher toggle: has this student been interviewed/picked this session.
    Stamps picked_at when marking, clears it when unmarking. Also appends a
    pick_event row so every pick/unpick is timestamped for post-hoc analysis
    (picked_at keeps only the latest; pick_event keeps the full history)."""
    ts = dt_to_db(now())
    with closing(connect()) as con:
        con.execute(
            "UPDATE tracked_student SET picked = ?, picked_at = ? WHERE studentID = ?",
            (1 if picked else 0, ts if picked else None, sid),
        )
        con.execute(
            "INSERT INTO pick_event (studentID, picked, ts) VALUES (?, ?, ?)",
            (sid, 1 if picked else 0, ts),
        )
        con.commit()


def add_note(student_id, text, trigger_id=None, trigger_type=None):
    """Append one note for a student. trigger_id/trigger_type are set when the
    note is written from an active alert; both None for a manual note. Returns
    the created row as a dict."""
    ts = dt_to_db(now())
    with closing(connect()) as con:
        cur = con.execute(
            "INSERT INTO note (studentID, ts, text, trigger_id, trigger_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, ts, text, trigger_id, trigger_type, ts),
        )
        nid = cur.lastrowid
        con.commit()
    return {
        "id": nid, "studentID": student_id, "ts": ts, "text": text,
        "trigger_id": trigger_id, "trigger_type": trigger_type, "created_at": ts,
    }


def list_notes(student_id):
    """All notes for a student, oldest first."""
    rows = _query(
        "SELECT id, studentID, ts, text, trigger_id, trigger_type, created_at "
        "FROM note WHERE studentID = ? ORDER BY ts, id",
        (student_id,),
    )
    return [dict(r) for r in rows]


def tracked_add(sid):
    """get_or_create: the daemon picks new rows up and backfills them."""
    _execute(
        "INSERT OR IGNORE INTO tracked_student (studentID, backfilled, created_at) "
        "VALUES (?, 0, ?)",
        (sid, dt_to_db(now())),
    )


def mark_backfilled(sid):
    _execute("UPDATE tracked_student SET backfilled = 1 WHERE studentID = ?", (sid,))


def tracked_remove(sid):
    """Stop tracking + delete the student's raw + derived data so they vanish."""
    with closing(connect()) as con:
        con.execute("BEGIN")
        try:
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
            con.commit()
        except Exception:
            con.rollback()
            raise


# ==========================================================================
# pipeline: cursor
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
# pipeline: raw logs (the only writer is the daemon's poller)
# ==========================================================================
def log_exists(source_event_id):
    if source_event_id is None:
        return False
    return bool(
        _query("SELECT 1 FROM vex_log WHERE source_event_id = ? LIMIT 1", (source_event_id,))
    )


def insert_message_and_log(norm):
    """Idempotent insert of one event (envelope + parsed log) in a transaction.
    Returns True if inserted, False if the UNIQUE source_event_id raced/duped."""
    with closing(connect()) as con:
        con.execute("BEGIN")
        try:
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
            con.commit()
            return True
        except sqlite3.IntegrityError:
            con.rollback()
            return False


def student_tail(sid, limit):
    """A student's most recent `limit` events (with envelope received_at for the
    timestamp fallback), oldest-first for chronological rehydration."""
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
# pipeline: materialized student state (daemon writes, API reads)
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
# pipeline: triggers
# ==========================================================================
def all_student_states():
    """Light projection the trigger evaluator iterates over."""
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
    """Run indices a big_change alert already fired for. Seeds a worker's
    in-memory dedupe set once on cold start, so it never re-alerts a run after a
    restart (and the trigger evaluator no longer scans history every tick)."""
    rows = _query(
        "SELECT json_extract(detail, '$.run_index') AS i FROM trigger_event "
        "WHERE studentID = ? AND trigger_type = 'big_change'",
        (student_id,),
    )
    return {r["i"] for r in rows if r["i"] is not None}
