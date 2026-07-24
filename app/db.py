"""
The whole data layer, on top of psycopg 3 talking to Postgres (no ORM).

Everything about the database is concentrated here: the schema, the pooled
connection, and every read and write the API and pipeline make. Keeping the SQL
in a single module is deliberate; it's the seam that made the move off SQLite a
self-contained rewrite of this file.

Who writes what: the daemon owns all the derived state, while the API is mostly
a reader that also makes a few small writes (the tracked roster, acks, notes,
control flags). Postgres MVCC lets the writer and the readers run at the same
time without blocking each other.

SQL dialect note: query bodies are written with `?` placeholders (a SQLite
legacy) and translated to psycopg's `%s` by _ph() in one place, so the ~40
functions below read unchanged. Postgres folds unquoted identifiers to lower
case, so the mixed-case column names (studentID, classCode, ...) come back
lower-cased; the row factory is case-insensitive so `r["studentID"]` still works.

Datetime contract: rows are stored as UTC-naive strings in the fixed-width
format '%Y-%m-%d %H:%M:%S.%f', a legacy of the original Django writer, kept as
Postgres `text` columns. Because the width is fixed, comparing the strings
lexically is the same as comparing the instants, which is what lets the cursor
and cutoff SQL (ORDER BY started_at, resolved_at >= cutoff) work on the text.
"""
import csv
import io
import json
import os
import threading
import time
import zipfile
from datetime import datetime, timezone

import psycopg
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL

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


def canon_id(sid):
    """Canonical identity key for a studentID: whitespace- and case-folded.
    studentIDs are handles, unique only within a class and sometimes typed in
    different casing (cobra3 vs Cobra3); folding here is what makes the whole
    system treat those spellings as one student. Derived tables are keyed on
    this; the raw most-recent casing is kept for display in
    student_state.display_id."""
    return (sid or "").strip().lower()


# --------------------------------------------------------------------------
# connection (a psycopg pool; each read/write borrows a connection and returns
# it, so the API's threadpool workers and the daemon get real concurrency via
# Postgres MVCC instead of contending on one shared handle)
# --------------------------------------------------------------------------
class _CIRow(dict):
    """A result row. Postgres lower-cases unquoted identifiers, so a column
    written as `studentID` comes back keyed `studentid`; this makes lookups
    case-insensitive so the ~40 query functions can keep reading r["studentID"].
    `dict(r)` yields the lower-cased keys as Postgres returns them, so the two
    call sites that leak column names into API JSON re-key explicitly."""

    def __getitem__(self, key):
        # Integer index -> positional access (dicts preserve column order), so the
        # few `row[0]` call sites keep working alongside `row["studentID"]`.
        if isinstance(key, int):
            return list(self.values())[key]
        try:
            return super().__getitem__(key)
        except KeyError:
            return super().__getitem__(key.lower())


def _ci_row_factory(cursor):
    cols = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: _CIRow(zip(cols, values))


def _configure(conn):
    conn.row_factory = _ci_row_factory


_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """The process-wide connection pool, opened on first use."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            if not DATABASE_URL:
                raise RuntimeError("DATABASE_URL is not set (see .env.mirror)")
            _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10,
                                   configure=_configure, open=True)
    return _pool


def _ph(sql):
    """Translate the `?` placeholders the query bodies use into psycopg's `%s`.
    Safe because no SQL string here contains a literal `%` or `?`."""
    return sql.replace("?", "%s")


def _query(sql, params=()):
    with _get_pool().connection() as con:
        return con.execute(_ph(sql), tuple(params)).fetchall()


def _execute(sql, params=()):
    """Run one self-contained write in its own transaction; returns the affected
    rowcount. The pooled connection commits on a clean block exit."""
    with _get_pool().connection() as con:
        cur = con.execute(_ph(sql), tuple(params))
        return cur.rowcount


class _TxnConn:
    """Wraps a borrowed psycopg connection so the multi-statement transaction
    bodies keep their `?`-placeholder `con.execute(...)` / `con.executemany(...)`
    calls. Postgres has no lastrowid, so inserts that need the new id use a
    `RETURNING id` clause and fetch it off the returned cursor."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql, params=()):
        return self._con.execute(_ph(sql), tuple(params))

    def executemany(self, sql, seq):
        cur = self._con.cursor()
        cur.executemany(_ph(sql), list(seq))
        return cur


class _WriteTxn:
    """Context manager for a multi-statement atomic write. Borrows a pooled
    connection whose context manager commits on a clean exit and rolls back if
    the block raises. Use it as `with db.write_txn() as con:`."""

    def __enter__(self):
        self._cm = _get_pool().connection()
        self._con = self._cm.__enter__()
        return _TxnConn(self._con)

    def __exit__(self, exc_type, exc, tb):
        return self._cm.__exit__(exc_type, exc, tb)


def write_txn():
    return _WriteTxn()


def data_version_probe():
    """A dedicated autocommit connection for the SSE change gate. Postgres has no
    global data_version, so data_version() below sums the channel_rev counters --
    every write bumps one of them via the schema triggers, so the sum changes iff
    something changed. Autocommit is essential: without it the connection would
    hold one snapshot and never see later commits. Caller owns closing it."""
    return psycopg.connect(DATABASE_URL, autocommit=True)


def data_version(con):
    """A monotonic 'did anything change at all?' number: the sum of the per-
    channel revision counters. One cheap read that the SSE loop polls so quiet
    ticks skip the per-channel fingerprint queries."""
    return con.execute("SELECT COALESCE(SUM(rev), 0) FROM channel_rev").fetchone()[0]


def latest_project(sid):
    """The most-recent non-empty project snapshot for a student (the raw project
    JSON string), or None. The detail view renders it into a readable program.
    Case-insensitive via the lower(studentID) index; newest by event time."""
    rows = _query(
        "SELECT project FROM vex_log WHERE lower(studentID) = ? "
        "AND project IS NOT NULL AND project != '' "
        "ORDER BY COALESCE(event_time, '') DESC, id DESC LIMIT 1",
        (canon_id(sid),))
    return rows[0]["project"] if rows else None


# --------------------------------------------------------------------------
# schema. A list of individual, idempotent statements (psycopg's extended
# protocol runs one command per execute(), so we don't concatenate them). Tables
# and indexes are IF NOT EXISTS; the change-counter function is CREATE OR
# REPLACE; its triggers are DROP IF EXISTS + CREATE. Safe to run every startup.
#
# Types vs the old SQLite schema: DATETIME columns are Postgres `text` (the
# fixed-width UTC-naive string contract is preserved, see the module docstring);
# BOOL columns are `smallint` holding 0/1 so the query bodies keep writing 1/0
# and reading ints; AUTOINCREMENT ids are identity columns.
# --------------------------------------------------------------------------
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS message (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        queue_name VARCHAR(255) NOT NULL,
        routing_key VARCHAR(255) NOT NULL DEFAULT '',
        exchange VARCHAR(255) NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        received_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS vex_log (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        from_message_id BIGINT NOT NULL REFERENCES message(id),
        classCode TEXT, eventType TEXT, studentID TEXT, project TEXT,
        raw_message TEXT, event_time TEXT,
        source_event_id BIGINT UNIQUE
    )""",
    "CREATE INDEX IF NOT EXISTS ix_vex_student ON vex_log(studentID, id)",
    # The case-insensitive fold queries vex_log by lower(studentID) (student_tail,
    # tracked_remove); a plain-column index can't serve an expression filter, so
    # without this every rehydrate is a full scan that grows with the log.
    "CREATE INDEX IF NOT EXISTS ix_vex_student_lower ON vex_log(lower(studentID))",
    "CREATE INDEX IF NOT EXISTS ix_vex_event_time ON vex_log(event_time)",
    """CREATE TABLE IF NOT EXISTS ingest_cursor (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name VARCHAR(32) NOT NULL UNIQUE,
        last_source_id BIGINT NOT NULL DEFAULT 0,
        last_event_time TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS student_state (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL UNIQUE,   -- canonical (folded) key; see canon_id
        display_id VARCHAR(128),                  -- most-recent raw casing, for the UI
        classCode VARCHAR(64),
        run_count INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
        runs TEXT, episodes TEXT,
        playground_prompt TEXT, playground_time TEXT,
        last_event_id BIGINT NOT NULL DEFAULT 0, last_event_time TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tracked_student (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL UNIQUE,
        backfilled SMALLINT NOT NULL DEFAULT 0,
        present SMALLINT NOT NULL DEFAULT 1,
        picked SMALLINT NOT NULL DEFAULT 0,
        picked_at TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS trigger_event (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL,
        trigger_type VARCHAR(24) NOT NULL,
        started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        resolved_at TEXT, acknowledged SMALLINT NOT NULL DEFAULT 0,
        detail TEXT, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_trig_student ON trigger_event(studentID, trigger_type)",
    "CREATE INDEX IF NOT EXISTS ix_trig_resolved ON trigger_event(resolved_at)",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )""",
    # Researcher login accounts (Phase 1 auth). username is the canonical (lower)
    # handle; password_hash is an argon2 hash (see app/auth.py). Never exported.
    """CREATE TABLE IF NOT EXISTS researcher (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        username VARCHAR(128) NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS note (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL,
        ts TEXT NOT NULL,
        text TEXT NOT NULL,
        trigger_id INTEGER,
        trigger_type VARCHAR(24),
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_note_student ON note(studentID, ts)",
    """CREATE TABLE IF NOT EXISTS pick_event (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL,
        picked SMALLINT NOT NULL,
        ts TEXT NOT NULL,
        source VARCHAR(32),          -- 'roster' | 'intervention' (NULL = pre-provenance)
        trigger_id INTEGER,          -- the trigger_event picked from; NULL for roster picks
        trigger_type VARCHAR(64)     -- its type, denormalized for readable exports
    )""",
    "CREATE INDEX IF NOT EXISTS ix_pick_student ON pick_event(studentID, ts)",
    """CREATE TABLE IF NOT EXISTS switch_event (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL,   -- the handle, in the casing seen at switch time
        kind VARCHAR(16) NOT NULL,         -- 'casing' | 'class'
        from_value TEXT,                   -- previous casing or classCode
        to_value TEXT,                     -- new casing or classCode
        ts TEXT NOT NULL,
        acknowledged SMALLINT NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_switch_ts ON switch_event(ts)",
    # Failed researcher inputs, parked verbatim so they are never lost. The
    # dashboard writes here (via /api/outbox/) only after a primary write has
    # failed its retries; rows carry the raw payload so any input can be replayed
    # by hand later. Deliberately NOT wiped by reset_all.
    """CREATE TABLE IF NOT EXISTS outbox (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        op VARCHAR(64) NOT NULL,           -- which action failed ('presence cobra3', ...)
        payload TEXT,                      -- the original request body, as JSON
        error TEXT,                        -- what the failure looked like client-side
        created_at TEXT NOT NULL
    )""",
    # Per-channel change counters for the SSE stream. Each row's rev is bumped by
    # the bump_rev() trigger whenever its source table changes, so data_fingerprint()
    # reads four fixed rows (O(1)) instead of scanning the tables (O(rows)).
    """CREATE TABLE IF NOT EXISTS channel_rev (
        channel TEXT PRIMARY KEY,
        rev BIGINT NOT NULL DEFAULT 0
    )""",
    # The seed just gives a defined start; bump_rev() upserts, so a channel is
    # self-healing even if the test harness truncates every table between tests.
    """INSERT INTO channel_rev (channel, rev) VALUES
        ('states', 0), ('triggers', 0), ('switches', 0), ('roster', 0)
        ON CONFLICT (channel) DO NOTHING""",
    # One trigger function, parameterized by channel name (TG_ARGV[0]); it bumps
    # the counter AND emits a NOTIFY so the SSE stream can LISTEN for low-latency
    # wakeups instead of polling (see app/main.py stream + data_version).
    """CREATE OR REPLACE FUNCTION bump_rev() RETURNS trigger AS $fn$
        BEGIN
            INSERT INTO channel_rev (channel, rev) VALUES (TG_ARGV[0], 1)
            ON CONFLICT (channel) DO UPDATE SET rev = channel_rev.rev + 1;
            PERFORM pg_notify('lm_change', TG_ARGV[0]);
            RETURN NULL;
        END;
    $fn$ LANGUAGE plpgsql""",
]

# (table, channel) pairs whose row-level INSERT/UPDATE/DELETE bump a counter.
_REV_TRIGGERS = [
    ("student_state", "states"),
    ("trigger_event", "triggers"),
    ("switch_event", "switches"),
    ("tracked_student", "roster"),
]


def init_db():
    """Create the schema and change-counter triggers. Idempotent, so it runs on
    every startup. On a fresh Postgres database this is the whole story; the
    SQLite era's in-place column migrations and one-time identity fold are gone
    (a fresh DB already has every column, and studentIDs are written canonically
    via canon_id, so there is nothing to fold)."""
    with _get_pool().connection() as con:
        for stmt in _SCHEMA:
            con.execute(stmt)
        for table, channel in _REV_TRIGGERS:
            con.execute(f"DROP TRIGGER IF EXISTS trg_rev_{channel} ON {table}")
            con.execute(
                f"CREATE TRIGGER trg_rev_{channel} "
                f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION bump_rev('{channel}')"
            )
        con.execute("INSERT INTO meta (key, value) VALUES ('idcanon_v1', '1') "
                    "ON CONFLICT (key) DO NOTHING")


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


def data_fingerprint():
    """A per-channel change signal for the SSE stream: a dict of channel name ->
    revision. Each rev is maintained by the channel_rev triggers, bumped once per
    write to the channel's source table, so this is an O(1) read of four fixed
    rows regardless of how large those tables grow -- not the O(rows) aggregate
    scan it used to be. Callers compare successive snapshots and never parse the
    value. Any of the four channels missing (fresh DB mid-migration) reads as 0."""
    revs = {r["channel"]: r["rev"] for r in _query("SELECT channel, rev FROM channel_rev")}
    return {c: str(revs.get(c, 0)) for c in ("states", "triggers", "switches", "roster")}


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
    """Clear the local mirror for a fresh session: raw events, derived state, the
    researcher notes, and the interview-pick state (the picked flags plus the
    pick/unpick history). Deliberately spared are the tracked roster itself, each
    student's presence flag, the ingest cursor, meta, and the failed-write
    outbox (parked inputs survive a reset) -- so the board keeps its
    students (and who's in the room) and rebuilds only from activity that arrives
    after the reset rather than re-pulling old events. The /api/reset/ endpoint
    writes a CSV backup (notes and pick history included) before calling this."""
    with write_txn() as con:
        for t in ("trigger_event", "student_state", "vex_log", "message", "note",
                  "pick_event", "switch_event"):
            con.execute(f"DELETE FROM {t}")
        # Clear the picked toggles but keep the roster + presence.
        con.execute("UPDATE tracked_student SET picked = 0, picked_at = NULL")


# --------------------------------------------------------------------------
# CSV export. Two callers share this: scripts/export_csv.py for an end-of-day
# dump, and the reset endpoint to snapshot everything before it wipes.
# --------------------------------------------------------------------------
# Tables excluded from the dump: the change-counter (channel_rev), the cursor
# bookkeeping (ingest_cursor), the control flags (meta), and the raw envelope
# (message), whose only research-relevant field is content, already copied into
# vex_log.raw_message.

_EXPORT_SKIP = {"channel_rev", "ingest_cursor", "meta", "message", "researcher"}


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


def _export_tables(con, tables):
    """Resolve which tables to dump: the caller's list, or every real table that
    isn't on the skip list."""
    if tables is not None:
        return tables
    return [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    ).fetchall() if r[0] not in _EXPORT_SKIP]


def _table_csv(con, table):
    """Render one table as a CSV string. Returns (csv_text, row_count). JSON
    columns come out as their raw JSON text; cells are flattened to one line."""
    cur = con.execute(f'SELECT * FROM "{table}"')
    cols = [d[0] for d in cur.description]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    n = 0
    for row in cur:
        w.writerow([_csv_value(cols[i], row[i]) for i in range(len(cols))])
        n += 1
    return buf.getvalue(), n


def export_csv(out_dir, tables=None, db_path=None):
    """Write one CSV file per table into out_dir (created if missing). Purely a
    read of the database, nothing is modified. Returns (out_dir, {table: rows})."""
    os.makedirs(out_dir, exist_ok=True)
    con = psycopg.connect(db_path or DATABASE_URL)
    try:
        written = {}
        for t in _export_tables(con, tables):
            text, n = _table_csv(con, t)
            with open(os.path.join(out_dir, f"{t}.csv"), "w", newline="", encoding="utf-8") as f:
                f.write(text)
            written[t] = n
        return out_dir, written
    finally:
        con.close()


def export_zip_bytes(tables=None, db_path=None):
    """Build an in-memory zip of one CSV per table and return its bytes. The same
    read-only snapshot as export_csv, but nothing touches the filesystem: the API
    streams these bytes straight to the browser as a download."""
    con = psycopg.connect(db_path or DATABASE_URL)
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for t in _export_tables(con, tables):
                text, _ = _table_csv(con, t)
                z.writestr(f"{t}.csv", text)
        return buf.getvalue()
    finally:
        con.close()


# --------------------------------------------------------------------------
# row shaping
# --------------------------------------------------------------------------
def _student_state_row(r):
    return {
        "studentID": r["studentID"],
        "display_id": r["display_id"],
        "classCode": r["classCode"],
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
        params += [canon_id(s) for s in students]
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


def trigger_history(sid, limit=100):
    """Every trigger ever fired for one student (since the last reset), newest
    first -- open, resolved, and dismissed alike. The detail modal renders this
    as the trigger-history grid, and the feed uses it to show each alert's
    previous trigger. Case-insensitive via the canonical key."""
    rows = _query(
        "SELECT * FROM trigger_event WHERE studentID = ? "
        "ORDER BY started_at DESC, id DESC LIMIT ?",
        (canon_id(sid), limit),
    )
    return [_trigger_row(r) for r in rows]


def ack_by_id(tid):
    return _execute("UPDATE trigger_event SET acknowledged = 1 WHERE id = ?", (tid,))


def ack_by_student(sid):
    return _execute(
        "UPDATE trigger_event SET acknowledged = 1 "
        "WHERE studentID = ? AND acknowledged = 0",
        (canon_id(sid),),
    )


def tracked_list():
    # A single LEFT JOIN rather than a roster query followed by per-student
    # lookups: has_data is just whether a matching student_state row exists.
    # studentID is UNIQUE on both tables, so the join is strictly 1:1.
    rows = _query(
        "SELECT t.studentID, t.backfilled, t.present, t.picked, t.picked_at, "
        "       s.display_id, (s.studentID IS NOT NULL) AS has_data "
        "FROM tracked_student t "
        "LEFT JOIN student_state s ON s.studentID = t.studentID "
        "ORDER BY t.studentID"
    )
    return [
        {
            "studentID": r["studentID"],                       # canonical key
            "display": r["display_id"] or r["studentID"],      # most-recent casing for the UI
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
        (1 if present else 0, canon_id(sid)),
    )


def set_picked(sid, picked, source="roster", trigger_id=None, trigger_type=None):
    """Researcher toggle for whether the student has been picked/interviewed this
    session. Marking stamps picked_at; unmarking clears it. Either way it also
    appends a pick_event row, so the full pick/unpick history is timestamped for
    later analysis (picked_at only holds the latest state; pick_event is the log).

    Provenance rides only on the log row: `source` is 'roster' (student card) or
    'intervention' (alert card), and trigger_id/trigger_type name the alert an
    intervention pick was clicked from (both None for roster picks)."""
    sid = canon_id(sid)
    ts = dt_to_db(now())
    with write_txn() as con:
        con.execute(
            "UPDATE tracked_student SET picked = ?, picked_at = ? WHERE studentID = ?",
            (1 if picked else 0, ts if picked else None, sid),
        )
        con.execute(
            "INSERT INTO pick_event (studentID, picked, ts, source, trigger_id, trigger_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, 1 if picked else 0, ts, source, trigger_id, trigger_type),
        )


def add_note(student_id, text, trigger_id=None, trigger_type=None):
    """Record one note for a student. Pass trigger_id/trigger_type to link it to
    the alert it was written from; leave both None for a free-standing manual
    note. Returns the new row as a dict."""
    student_id = canon_id(student_id)
    ts = dt_to_db(now())
    with write_txn() as con:
        cur = con.execute(
            "INSERT INTO note (studentID, ts, text, trigger_id, trigger_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (student_id, ts, text, trigger_id, trigger_type, ts),
        )
        nid = cur.fetchone()["id"]
    return {
        "id": nid, "studentID": student_id, "ts": ts, "text": text,
        "trigger_id": trigger_id, "trigger_type": trigger_type, "created_at": ts,
    }


def list_notes(student_id):
    """Every note for a student, in chronological order."""
    rows = _query(
        "SELECT id, studentID, ts, text, trigger_id, trigger_type, created_at "
        "FROM note WHERE studentID = ? ORDER BY ts, id",
        (canon_id(student_id),),
    )
    # Explicit keys, not dict(r): Postgres returns lower-cased column names, and
    # this dict is serialized straight to API JSON where the UI expects studentID.
    return [
        {
            "id": r["id"], "studentID": r["studentID"], "ts": r["ts"],
            "text": r["text"], "trigger_id": r["trigger_id"],
            "trigger_type": r["trigger_type"], "created_at": r["created_at"],
        }
        for r in rows
    ]


# --------------------------------------------------------------------------
# switch_event: casing/class switches the daemon detects for a tracked student.
# The dashboard shows a toast + a reviewable feed off these rows.
# --------------------------------------------------------------------------
def record_switch(student_id, kind, from_value, to_value):
    """Append one detected switch. `kind` is 'casing' or 'class'."""
    _execute(
        "INSERT INTO switch_event (studentID, kind, from_value, to_value, ts) "
        "VALUES (?, ?, ?, ?, ?)",
        (student_id, kind, from_value, to_value, dt_to_db(now())),
    )


def record_outbox(op, payload, error):
    """Park a researcher input whose primary write failed, verbatim, so it can
    be replayed by hand later. `payload` is the original request body (already a
    JSON string, or None)."""
    _execute(
        "INSERT INTO outbox (op, payload, error, created_at) VALUES (?, ?, ?, ?)",
        (op, payload, error, dt_to_db(now())),
    )


def list_outbox(limit=200):
    """Parked failed inputs, newest first."""
    rows = _query(
        "SELECT id, op, payload, error, created_at FROM outbox "
        "ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def list_switches(limit=100, unacked_only=False):
    """Recent switches, newest first. `unacked_only` keeps just the ones not yet
    dismissed (what the live toast/feed wants)."""
    where = "WHERE acknowledged = 0 " if unacked_only else ""
    rows = _query(
        "SELECT id, studentID, kind, from_value, to_value, ts, acknowledged "
        f"FROM switch_event {where}ORDER BY ts DESC, id DESC LIMIT ?",
        (limit,),
    )
    # Explicit keys (see list_notes): preserve the studentID casing the UI expects.
    return [
        {
            "id": r["id"], "studentID": r["studentID"], "kind": r["kind"],
            "from_value": r["from_value"], "to_value": r["to_value"],
            "ts": r["ts"], "acknowledged": r["acknowledged"],
        }
        for r in rows
    ]


def ack_switch(switch_id):
    """Dismiss one switch by id so it stops showing as new."""
    return _execute("UPDATE switch_event SET acknowledged = 1 WHERE id = ?", (switch_id,))


def tracked_add(sid):
    """Add a student to the roster (no-op if already there). The daemon notices
    the new, not-yet-backfilled row on its next tick and pulls their history."""
    _execute(
        "INSERT INTO tracked_student (studentID, backfilled, created_at) "
        "VALUES (?, 0, ?) ON CONFLICT (studentID) DO NOTHING",
        (canon_id(sid), dt_to_db(now())),
    )


def mark_backfilled(sid):
    _execute("UPDATE tracked_student SET backfilled = 1 WHERE studentID = ?", (canon_id(sid),))


def tracked_remove(sid):
    """Untrack a student and delete everything tied to them, raw events and
    derived state alike, so they disappear from the board entirely."""
    sid = canon_id(sid)
    with write_txn() as con:
        # vex_log keeps the raw casing prod sent, so match it case-insensitively;
        # the derived/roster tables are already keyed on the canonical id.
        msg_ids = [
            row[0]
            for row in con.execute(
                "SELECT from_message_id FROM vex_log WHERE lower(studentID) = ?", (sid,)
            ).fetchall()
        ]
        con.execute("DELETE FROM vex_log WHERE lower(studentID) = ?", (sid,))
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
                "VALUES ('pipeline', '', '', ?, ?) RETURNING id",
                (norm["raw_message"], dt_to_db(norm["event_time"] or now())),
            )
            message_id = cur.fetchone()["id"]
            con.execute(
                "INSERT INTO vex_log "
                "(from_message_id, classCode, eventType, studentID, project, raw_message, "
                " event_time, source_event_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
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
    except psycopg.errors.UniqueViolation:
        return False


def student_tail(sid, limit, since=None):
    """A student's last `limit` events, returned oldest-first so a worker can
    replay them in order on rehydrate. Joins in the envelope's received_at to use
    as a timestamp fallback when the parsed event_time is missing. `since` (a UTC
    datetime, or None) hides events from before the session: rows whose timestamp
    is earlier are filtered out, so a returning student's prior session stays in
    the log but never replays into the live view."""
    # vex_log stores the raw casing; the worker keys on the canonical id, so match
    # case-insensitively to pull every spelling of the handle.
    where, params = "lower(v.studentID) = ?", [canon_id(sid)]
    if since is not None:
        # Stored datetimes are fixed-width strings, so a lexical >= is chronological.
        where += " AND COALESCE(v.event_time, m.received_at) >= ?"
        params.append(dt_to_db(since))

    # Order by event time, not v.id: backfill inserts page_student's newest-first
    # results, so id is reverse-chronological. COALESCE matches the `since` filter
    # (received_at fallback when event_time is null); v.id is a stable tiebreak.
    # DESC + LIMIT keeps the most-recent `limit` events; the reversed() below flips
    # them to oldest-first for replay.
    
    order_by = "ORDER BY COALESCE(v.event_time, m.received_at) DESC, v.id DESC"
    rows = _query(
        "SELECT v.studentID, v.eventType, v.classCode, v.project, v.raw_message, v.event_time, "
        "       v.source_event_id, m.received_at "
        "FROM vex_log v LEFT JOIN message m ON m.id = v.from_message_id "
        f"WHERE {where} {order_by} LIMIT ?",
        (*params, limit),
    )
    out = []
    for r in reversed(rows):
        out.append(
            {
                "studentID": r["studentID"],
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
    sustained-trigger sweep (inactive) needs."""
    rows = _query("SELECT studentID, last_event_time FROM student_state")
    return [
        {"studentID": r["studentID"], "last_event_time": db_to_dt(r["last_event_time"])}
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


def fired_indices(student_id, trigger_type):
    """Run indices that already produced a momentary trigger of this type. A worker
    loads these once on cold start to seed its in-memory dedupe, so a restart never
    re-fires an old run and the trigger sweep needn't re-scan history."""
    rows = _query(
        "SELECT (detail::jsonb ->> 'run_index')::int AS i FROM trigger_event "
        "WHERE studentID = ? AND trigger_type = ?",
        (student_id, trigger_type),
    )
    return {r["i"] for r in rows if r["i"] is not None}


# ==========================================================================
# Researcher accounts (Phase 1 auth). Password hashing/verification lives in
# app/auth.py; this module only stores and reads the rows.
# ==========================================================================
def upsert_researcher(username, password_hash):
    """Create a researcher, or reset an existing one's password. username is
    folded to the canonical (lower) key. Returns the researcher id."""
    row = _query(
        "INSERT INTO researcher (username, password_hash, created_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT (username) DO UPDATE SET password_hash = excluded.password_hash "
        "RETURNING id",
        (canon_id(username), password_hash, dt_to_db(now())),
    )
    return row[0]["id"]


def get_researcher_by_username(username):
    """The row (id, username, password_hash) for a login lookup, or None."""
    rows = _query(
        "SELECT id, username, password_hash FROM researcher WHERE username = ?",
        (canon_id(username),),
    )
    return dict(rows[0]) if rows else None


def get_researcher_by_id(researcher_id):
    """The row (id, username) a session resolves to, or None."""
    rows = _query(
        "SELECT id, username FROM researcher WHERE id = ?", (researcher_id,))
    return dict(rows[0]) if rows else None
