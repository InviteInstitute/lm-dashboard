"""
The whole data layer, on top of psycopg 3 talking to Postgres (no ORM).

Everything about the database is concentrated here: the schema, the pooled
connection, and every read and write the API and pipeline make.

Who writes what: the daemon owns all the derived state, while the API is mostly
a reader that also makes a few small writes (the tracked roster, acks, notes,
control flags). Postgres MVCC lets the writer and the readers run at the same
time without blocking each other.

Rows come back as dicts keyed the way Postgres names the columns. It folds
unquoted identifiers to lower case, so `studentID` is read as r["studentid"].
Timestamps are `timestamptz` and come back as aware UTC datetimes.
"""

import csv
import io
import json
import threading
import zipfile
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL


def now():
    return datetime.now(UTC)


def _json(s):
    return json.loads(s) if s else None


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
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """The process-wide connection pool, opened on first use. Sessions run in
    UTC so timestamps read back with a +00:00 offset."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            if not DATABASE_URL:
                raise RuntimeError("DATABASE_URL is not set (see .env.mirror)")
            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                kwargs={"row_factory": dict_row, "options": "-c TimeZone=UTC"},
                open=True,
            )
    return _pool


def _query(sql, params=()):
    with _get_pool().connection() as con:
        return con.execute(sql, params).fetchall()


def _execute(sql, params=()):
    """Run one self-contained write in its own transaction; returns the affected
    rowcount. The pooled connection commits on a clean block exit."""
    with _get_pool().connection() as con:
        return con.execute(sql, params).rowcount


def write_txn():
    """A multi-statement atomic write: `with db.write_txn() as con:` commits on a
    clean exit and rolls back if the block raises."""
    return _get_pool().connection()


def latest_project(sid):
    """The most-recent non-empty project snapshot for a student (the raw project
    JSON string), or None. The detail view renders it into a readable program.
    Case-insensitive via the lower(studentID) index; newest by event time."""
    rows = _query(
        "SELECT project FROM vex_log WHERE lower(studentID) = %s "
        "AND project IS NOT NULL AND project != '' "
        "ORDER BY event_time DESC NULLS LAST, id DESC LIMIT 1",
        (canon_id(sid),),
    )
    return rows[0]["project"] if rows else None


# --------------------------------------------------------------------------
# schema. A list of individual, idempotent statements (psycopg's extended
# protocol runs one command per execute(), so we don't concatenate them). Tables
# and indexes are IF NOT EXISTS, the change-counter function is CREATE OR
# REPLACE, and its triggers are DROP IF EXISTS + CREATE. Safe to run every startup.
# --------------------------------------------------------------------------
# One-time conversion of a database made before the columns had native types:
# timestamps were TEXT in UTC with no zone ('2026-11-25 09:40:38.112132') and
# flags were SMALLINT 0/1. It runs inside init_db's transaction, so it applies
# whole or not at all, and it does nothing once trigger_event.started_at is no
# longer text. A board's reset_at setting was the same naive text, so it is
# rewritten as ISO with an offset, as reset_since reads it.
_NATIVE_TYPES = """DO $mig$ BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'trigger_event'
          AND column_name = 'started_at') = 'text' THEN
        PERFORM set_config('TimeZone', 'UTC', true);
        ALTER TABLE workspace
            ALTER COLUMN created_at TYPE timestamptz USING NULLIF(created_at, '')::timestamptz;
        ALTER TABLE message
            ALTER COLUMN received_at TYPE timestamptz USING NULLIF(received_at, '')::timestamptz;
        ALTER TABLE vex_log
            ALTER COLUMN event_time TYPE timestamptz USING NULLIF(event_time, '')::timestamptz;
        ALTER TABLE ingest_cursor
            ALTER COLUMN last_event_time TYPE timestamptz USING NULLIF(last_event_time, '')::timestamptz,
            ALTER COLUMN updated_at TYPE timestamptz USING NULLIF(updated_at, '')::timestamptz;
        ALTER TABLE student_state
            ALTER COLUMN playground_time TYPE timestamptz USING NULLIF(playground_time, '')::timestamptz,
            ALTER COLUMN last_event_time TYPE timestamptz USING NULLIF(last_event_time, '')::timestamptz,
            ALTER COLUMN updated_at TYPE timestamptz USING NULLIF(updated_at, '')::timestamptz;
        ALTER TABLE goal_profile
            ALTER COLUMN updated_at TYPE timestamptz USING NULLIF(updated_at, '')::timestamptz;
        ALTER TABLE tracked_student
            ALTER COLUMN picked_at TYPE timestamptz USING NULLIF(picked_at, '')::timestamptz,
            ALTER COLUMN created_at TYPE timestamptz USING NULLIF(created_at, '')::timestamptz,
            ALTER COLUMN backfilled DROP DEFAULT,
            ALTER COLUMN backfilled TYPE boolean USING backfilled <> 0,
            ALTER COLUMN backfilled SET DEFAULT false,
            ALTER COLUMN present DROP DEFAULT,
            ALTER COLUMN present TYPE boolean USING present <> 0,
            ALTER COLUMN present SET DEFAULT true,
            ALTER COLUMN picked DROP DEFAULT,
            ALTER COLUMN picked TYPE boolean USING picked <> 0,
            ALTER COLUMN picked SET DEFAULT false;
        ALTER TABLE trigger_event
            ALTER COLUMN started_at TYPE timestamptz USING NULLIF(started_at, '')::timestamptz,
            ALTER COLUMN last_seen_at TYPE timestamptz USING NULLIF(last_seen_at, '')::timestamptz,
            ALTER COLUMN resolved_at TYPE timestamptz USING NULLIF(resolved_at, '')::timestamptz,
            ALTER COLUMN created_at TYPE timestamptz USING NULLIF(created_at, '')::timestamptz,
            ALTER COLUMN acknowledged DROP DEFAULT,
            ALTER COLUMN acknowledged TYPE boolean USING acknowledged <> 0,
            ALTER COLUMN acknowledged SET DEFAULT false;
        ALTER TABLE trigger_ack
            ALTER COLUMN ts TYPE timestamptz USING NULLIF(ts, '')::timestamptz;
        ALTER TABLE note
            ALTER COLUMN ts TYPE timestamptz USING NULLIF(ts, '')::timestamptz,
            ALTER COLUMN created_at TYPE timestamptz USING NULLIF(created_at, '')::timestamptz;
        ALTER TABLE pick_event
            ALTER COLUMN ts TYPE timestamptz USING NULLIF(ts, '')::timestamptz,
            ALTER COLUMN picked TYPE boolean USING picked <> 0;
        ALTER TABLE switch_event
            ALTER COLUMN ts TYPE timestamptz USING NULLIF(ts, '')::timestamptz,
            ALTER COLUMN acknowledged DROP DEFAULT,
            ALTER COLUMN acknowledged TYPE boolean USING acknowledged <> 0,
            ALTER COLUMN acknowledged SET DEFAULT false;
        ALTER TABLE outbox
            ALTER COLUMN created_at TYPE timestamptz USING NULLIF(created_at, '')::timestamptz;
        UPDATE workspace_setting SET value = to_char(
            value::timestamp, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'
        ) WHERE key = 'reset_at' AND value !~ '[+Z]';
    END IF;
END $mig$"""

_SCHEMA = [
    # Tenancy. A workspace is one browser's isolated board (its roster,
    # notes, picks and settings). The per-student raw mirror + derived analysis
    # (vex_log, student_state, trigger_event, ...) stay global. Created before
    # the per-room tables that reference workspace(id).
    """CREATE TABLE IF NOT EXISTS workspace (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        client_key VARCHAR(64) UNIQUE   -- browser/device key for per-browser boards; NULL for named/default
    )""",
    """CREATE TABLE IF NOT EXISTS message (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        queue_name VARCHAR(255) NOT NULL,
        routing_key VARCHAR(255) NOT NULL DEFAULT '',
        exchange VARCHAR(255) NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        received_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS vex_log (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        from_message_id BIGINT NOT NULL REFERENCES message(id),
        classCode TEXT, eventType TEXT, studentID TEXT, project TEXT,
        raw_message TEXT, event_time TIMESTAMPTZ,
        source_event_id BIGINT UNIQUE
    )""",
    "CREATE INDEX IF NOT EXISTS ix_vex_student ON vex_log(studentID, id)",
    # The case-insensitive fold queries vex_log by lower(studentID) (student_tail,
    # tracked_remove); a plain-column index can't serve an expression filter, so
    # without this every rehydrate is a full scan that grows with the log.
    "CREATE INDEX IF NOT EXISTS ix_vex_student_lower ON vex_log(lower(studentID))",
    "CREATE INDEX IF NOT EXISTS ix_vex_event_time ON vex_log(event_time)",
    # A ZANY row (app/zany.py) is keyed by its seq in ATLAS's log store; its source_event_id
    # stays NULL, since a ZANY record's own id only counts within one page session.
    "ALTER TABLE vex_log ADD COLUMN IF NOT EXISTS zany_seq BIGINT",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_vex_zany_seq ON vex_log(zany_seq)",
    """CREATE TABLE IF NOT EXISTS ingest_cursor (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name VARCHAR(32) NOT NULL UNIQUE,
        last_source_id BIGINT NOT NULL DEFAULT 0,
        last_event_time TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS student_state (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL UNIQUE,   -- canonical (folded) key; see canon_id
        display_id VARCHAR(128),                  -- most-recent raw casing, for the UI
        classCode VARCHAR(64),
        run_count INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
        runs TEXT, episodes TEXT,
        playground_prompt TEXT, playground_time TIMESTAMPTZ,
        last_event_id BIGINT NOT NULL DEFAULT 0, last_event_time TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    # goal_profile is shared (daemon-written per student), one row per profiled
    # run. run_index lines up with student_state.runs[i] (same event buffer), so
    # the detail view joins goal evidence to the edit-distance run. run_index
    # restarts at 0 every daemon session, so a row is keyed by session too.
    # profile holds the full goal_strategy result dict as JSON.
    """CREATE TABLE IF NOT EXISTS goal_profile (
        studentID VARCHAR(128) NOT NULL,          -- canonical (folded) key; see canon_id
        session TEXT NOT NULL DEFAULT '',         -- daemon session the run_index belongs to
        run_index INTEGER NOT NULL,
        playground VARCHAR(64),
        status VARCHAR(32),
        ts DOUBLE PRECISION,
        profile TEXT NOT NULL,                    -- json.dumps of the goal result dict
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (studentID, session, run_index)
    )""",
    # tracked_student is per-workspace: which students a workspace's board tracks,
    # plus that workspace's presence/picked state for them. Same student in two
    # workspaces = two rows, so the roster is isolated (UNIQUE per workspace).
    """CREATE TABLE IF NOT EXISTS tracked_student (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        workspace_id BIGINT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        studentID VARCHAR(128) NOT NULL,
        backfilled BOOLEAN NOT NULL DEFAULT false,
        present BOOLEAN NOT NULL DEFAULT true,
        picked BOOLEAN NOT NULL DEFAULT false,
        picked_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL,
        UNIQUE (workspace_id, studentID)
    )""",
    """CREATE TABLE IF NOT EXISTS trigger_event (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL,
        trigger_type VARCHAR(24) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL, last_seen_at TIMESTAMPTZ NOT NULL,
        resolved_at TIMESTAMPTZ, acknowledged BOOLEAN NOT NULL DEFAULT false,
        detail TEXT, created_at TIMESTAMPTZ NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_trig_student ON trigger_event(studentID, trigger_type)",
    "CREATE INDEX IF NOT EXISTS ix_trig_resolved ON trigger_event(resolved_at)",
    # trigger_event is shared (one row per student's alert, written by the daemon).
    # Display acknowledgement is per-workspace, so a row here means "this workspace
    # has dismissed this trigger". trigger_event.acknowledged is the global flag
    # the daemon's re-alert logic reads (app/pipeline/triggers.py).
    """CREATE TABLE IF NOT EXISTS trigger_ack (
        workspace_id BIGINT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        trigger_id BIGINT NOT NULL REFERENCES trigger_event(id) ON DELETE CASCADE,
        ts TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (workspace_id, trigger_id)
    )""",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )""",
    # Per-workspace control flags (polling_enabled, viewer_last_seen, source,
    # disabled_triggers, reset_at), one row per board and key.
    """CREATE TABLE IF NOT EXISTS workspace_setting (
        workspace_id BIGINT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value TEXT,
        PRIMARY KEY (workspace_id, key)
    )""",
    # note/pick_event/switch_event are researcher-owned, so per-workspace.
    """CREATE TABLE IF NOT EXISTS note (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        workspace_id BIGINT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        studentID VARCHAR(128) NOT NULL,
        ts TIMESTAMPTZ NOT NULL,
        text TEXT NOT NULL,
        trigger_id INTEGER,
        trigger_type VARCHAR(24),
        created_at TIMESTAMPTZ NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_note_student ON note(workspace_id, studentID, ts)",
    """CREATE TABLE IF NOT EXISTS pick_event (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        workspace_id BIGINT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        studentID VARCHAR(128) NOT NULL,
        picked BOOLEAN NOT NULL,
        ts TIMESTAMPTZ NOT NULL,
        source VARCHAR(32),          -- 'roster' | 'intervention' (NULL = pre-provenance)
        trigger_id INTEGER,          -- the trigger_event picked from; NULL for roster picks
        trigger_type VARCHAR(64)     -- its type, denormalized for readable exports
    )""",
    "CREATE INDEX IF NOT EXISTS ix_pick_student ON pick_event(workspace_id, studentID, ts)",
    # switch_event is daemon-detected per student (casing/class changes), so it's
    # shared like the rest of the mirror; the feed is scoped by the workspace
    # roster and ack stays global (a low-stakes toast feature).
    """CREATE TABLE IF NOT EXISTS switch_event (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        studentID VARCHAR(128) NOT NULL,   -- the handle, in the casing seen at switch time
        kind VARCHAR(16) NOT NULL,         -- 'casing' | 'class'
        from_value TEXT,                   -- previous casing or classCode
        to_value TEXT,                     -- new casing or classCode
        ts TIMESTAMPTZ NOT NULL,
        acknowledged BOOLEAN NOT NULL DEFAULT false
    )""",
    "CREATE INDEX IF NOT EXISTS ix_switch_ts ON switch_event(ts)",
    # Failed researcher inputs, parked verbatim so they are never lost. The
    # dashboard writes here (via /api/outbox/) only after a primary write has
    # failed its retries; rows carry the raw payload so any input can be replayed
    # by hand later. Deliberately NOT wiped by a reset. Per-workspace.
    """CREATE TABLE IF NOT EXISTS outbox (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        workspace_id BIGINT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        op VARCHAR(64) NOT NULL,           -- which action failed ('presence cobra3', ...)
        payload TEXT,                      -- the original request body, as JSON
        error TEXT,                        -- what the failure looked like client-side
        created_at TIMESTAMPTZ NOT NULL
    )""",
    _NATIVE_TYPES,
    # Per-channel change counters for the SSE stream. bump_rev() upserts a
    # channel's row whenever its source table changes, so data_fingerprint()
    # reads a handful of rows instead of scanning the tables.
    """CREATE TABLE IF NOT EXISTS channel_rev (
        channel TEXT PRIMARY KEY,
        rev BIGINT NOT NULL DEFAULT 0
    )""",
    # One trigger function, parameterized by channel name (TG_ARGV[0]).
    """CREATE OR REPLACE FUNCTION bump_rev() RETURNS trigger AS $fn$
        BEGIN
            INSERT INTO channel_rev (channel, rev) VALUES (TG_ARGV[0], 1)
            ON CONFLICT (channel) DO UPDATE SET rev = channel_rev.rev + 1;
            RETURN NULL;
        END;
    $fn$ LANGUAGE plpgsql""",
]

# (table, channel) pairs whose row-level INSERT/UPDATE/DELETE bump a counter.
_REV_TRIGGERS = [
    ("student_state", "states"),
    # Goal profiles are written after the student_state row, so they signal the
    # same channel; else an open sheet refetches before the newest run's evidence.
    ("goal_profile", "states"),
    ("trigger_event", "triggers"),
    ("switch_event", "switches"),
    ("tracked_student", "roster"),
]


def init_db():
    """Create the schema and change-counter triggers. Idempotent, so it runs on
    every startup."""
    with _get_pool().connection() as con:
        # The API and the daemon start together. One at a time, so the type
        # conversion and the trigger swaps never race.
        con.execute("SELECT pg_advisory_xact_lock(4210)")
        for stmt in _SCHEMA:
            con.execute(stmt)
        for table, channel in _REV_TRIGGERS:
            con.execute(f"DROP TRIGGER IF EXISTS trg_rev_{channel} ON {table}")
            con.execute(
                f"CREATE TRIGGER trg_rev_{channel} "
                f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION bump_rev('{channel}')"
            )
    ensure_default_workspace()


# --------------------------------------------------------------------------
# tenancy. A workspace is one browser's isolated board, found by the board id
# the browser sends (workspace_for_client_key). `default_workspace_id()` is the
# shared board for clients that send none (scripts, tests), and the fallback
# for writes that name no workspace.
# --------------------------------------------------------------------------
DEFAULT_WORKSPACE = "default"


def ensure_default_workspace():
    """Create the implicit 'default' workspace if it's missing. Idempotent."""
    _execute(
        "INSERT INTO workspace (name, created_at) SELECT %s, %s "
        "WHERE NOT EXISTS (SELECT 1 FROM workspace WHERE name = %s)",
        (DEFAULT_WORKSPACE, now(), DEFAULT_WORKSPACE),
    )


def default_workspace_id():
    """Id of the 'default' workspace. Not cached: the test harness truncates and
    reseeds it, so the id can change between tests; a PK-ish lookup is cheap."""
    rows = _query("SELECT id FROM workspace WHERE name = %s", (DEFAULT_WORKSPACE,))
    return rows[0]["id"] if rows else None


def _ws(workspace_id):
    """Resolve a workspace id, falling back to the default workspace."""
    return workspace_id if workspace_id is not None else default_workspace_id()


def workspace_for_client_key(client_key):
    """Get-or-create the workspace bound to a browser/device key. This is how
    per-browser isolation works under a shared login: the same key (persisted in
    the browser's localStorage) always resolves to the same board, and a new
    browser gets a fresh one. This runs on every API request, so the common case
    (an existing board) is a single cheap SELECT with no write; only a genuinely
    new board inserts. Race-safe via the client_key unique constraint."""
    rows = _query("SELECT id FROM workspace WHERE client_key = %s", (client_key,))
    if rows:
        return rows[0]["id"]
    # New board. ON CONFLICT DO NOTHING absorbs a concurrent create; RETURNING
    # gives the row on our own insert, and we re-read if a racing request won.
    rows = _query(
        "INSERT INTO workspace (name, created_at, client_key) VALUES (%s, %s, %s) "
        "ON CONFLICT (client_key) DO NOTHING RETURNING id",
        (f"browser {client_key[:8]}", now(), client_key),
    )
    if rows:
        return rows[0]["id"]
    return _query("SELECT id FROM workspace WHERE client_key = %s", (client_key,))[0]["id"]


def tracked_union():
    """Distinct students tracked by ANY workspace, with whether any of their
    roster rows still needs a one-time history backfill. The
    daemon ingests this union -- one shared mirror per student regardless of how
    many boards watch them."""
    rows = _query(
        "SELECT studentID, bool_and(backfilled) AS backfilled "
        "FROM tracked_student GROUP BY studentID ORDER BY studentID"
    )
    return [{"studentID": r["studentid"], "backfilled": r["backfilled"]} for r in rows]


def students_in_workspaces(workspace_ids):
    """The set of students tracked by any of the given workspaces (the prod-poll
    allowlist: the union of the LIVE boards' rosters)."""
    rows = _query(
        "SELECT DISTINCT studentID FROM tracked_student WHERE workspace_id = ANY(%s)",
        (list(workspace_ids),),
    )
    return {r["studentid"] for r in rows}


def workspace_polling_states():
    """Per-workspace polling control for the daemon: (id, polling_enabled,
    viewer_last_seen) for every workspace, pivoted from workspace_setting."""
    rows = _query(
        "SELECT w.id, "
        "  MAX(CASE WHEN s.key = 'polling_enabled' THEN s.value END) AS polling_enabled, "
        "  MAX(CASE WHEN s.key = 'viewer_last_seen' THEN s.value END) AS viewer_last_seen "
        "FROM workspace w LEFT JOIN workspace_setting s ON s.workspace_id = w.id "
        "GROUP BY w.id ORDER BY w.id"
    )
    return [
        {
            "id": r["id"],
            "polling_enabled": r["polling_enabled"],
            "viewer_last_seen": r["viewer_last_seen"],
        }
        for r in rows
    ]


# Per-workspace control flags (polling_enabled, viewer_last_seen, disabled_triggers,
# source, reset_at).
def set_workspace_setting(workspace_id, key, value):
    _execute(
        "INSERT INTO workspace_setting (workspace_id, key, value) VALUES (%s, %s, %s) "
        "ON CONFLICT (workspace_id, key) DO UPDATE SET value = excluded.value",
        (_ws(workspace_id), key, value),
    )


def get_workspace_setting(workspace_id, key):
    rows = _query(
        "SELECT value FROM workspace_setting WHERE workspace_id = %s AND key = %s",
        (_ws(workspace_id), key),
    )
    return rows[0]["value"] if rows else None


# --------------------------------------------------------------------------
# meta: a tiny key/value store the two processes use to signal each other
# (the daemon's session start)
# --------------------------------------------------------------------------
# The daemon's current session (see workers.start_session).
SESSION_META_KEY = "session_start"


def set_meta(key, value):
    _execute(
        "INSERT INTO meta (key, value) VALUES (%s, %s) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(key):
    rows = _query("SELECT value FROM meta WHERE key = %s", (key,))
    return rows[0]["value"] if rows else None


def data_fingerprint():
    """A per-channel change signal for the SSE stream: a dict of channel name ->
    revision. Each rev is bumped by the channel_rev triggers once per write to
    the channel's source table, so this reads a handful of rows however large
    those tables grow. Callers compare successive snapshots and never parse the
    value. A channel with no writes yet has no row and is simply absent."""
    return {r["channel"]: str(r["rev"]) for r in _query("SELECT channel, rev FROM channel_rev")}


RESET_AT_KEY = "reset_at"


def reset_since(workspace_id=None):
    """When this workspace was last reset (a UTC datetime), or None. Every read
    behind the student tile shows only activity from then on."""
    value = get_workspace_setting(workspace_id, RESET_AT_KEY)
    return datetime.fromisoformat(value) if value else None


def reset_workspace(workspace_id=None):
    """Clear one workspace's researcher-owned state for a fresh session: its
    notes, pick history + picked flags, and trigger acks. Spared: the roster
    itself and presence, and the SHARED per-student mirror + derived state
    (vex_log, student_state, trigger_event), which other boards depend on and
    which this board just re-derives its view from. The /api/reset/ endpoint
    saves an export zip before calling this."""
    wsid = _ws(workspace_id)
    with write_txn() as con:
        con.execute("DELETE FROM note WHERE workspace_id = %s", (wsid,))
        con.execute("DELETE FROM pick_event WHERE workspace_id = %s", (wsid,))
        con.execute("DELETE FROM trigger_ack WHERE workspace_id = %s", (wsid,))
        # Clear the picked toggles but keep the roster + presence.
        con.execute(
            "UPDATE tracked_student SET picked = false, picked_at = NULL WHERE workspace_id = %s",
            (wsid,),
        )
        # The shared activity stays, but this board stops showing anything from
        # before now: runs, episodes, goal evidence, alerts, trigger history and
        # switches all read from this moment on (see reset_since).
        con.execute(
            "INSERT INTO workspace_setting (workspace_id, key, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (workspace_id, key) DO UPDATE SET value = excluded.value",
            (wsid, RESET_AT_KEY, now().isoformat()),
        )


# --------------------------------------------------------------------------
# CSV export, scoped to one workspace. Two callers: the Export button, and the
# reset endpoint to snapshot a board before it wipes.
# Per-workspace tables filter on workspace_id; the shared per-student tables
# (student_state, trigger_event, switch_event, vex_log) filter on that board's
# roster. Skipped entirely: control/bookkeeping tables and the raw message
# envelope (its content is already in vex_log.raw_message).
# --------------------------------------------------------------------------
def _workspace_export_queries(workspace_id):
    """{table: (sql, params)} for a workspace-scoped CSV dump."""
    ws = workspace_id
    roster = "studentID IN (SELECT studentID FROM tracked_student WHERE workspace_id = %s)"
    vex_roster = (
        "lower(studentID) IN (SELECT studentID FROM tracked_student WHERE workspace_id = %s)"
    )
    return {
        "tracked_student": ("SELECT * FROM tracked_student WHERE workspace_id = %s", (ws,)),
        "note": ("SELECT * FROM note WHERE workspace_id = %s", (ws,)),
        "pick_event": ("SELECT * FROM pick_event WHERE workspace_id = %s", (ws,)),
        "trigger_ack": ("SELECT * FROM trigger_ack WHERE workspace_id = %s", (ws,)),
        "outbox": ("SELECT * FROM outbox WHERE workspace_id = %s", (ws,)),
        "student_state": (f"SELECT * FROM student_state WHERE {roster}", (ws,)),
        "trigger_event": (f"SELECT * FROM trigger_event WHERE {roster}", (ws,)),
        "switch_event": (f"SELECT * FROM switch_event WHERE {roster}", (ws,)),
        "goal_profile": (f"SELECT * FROM goal_profile WHERE {roster}", (ws,)),
        "vex_log": (f"SELECT * FROM vex_log WHERE {vex_roster}", (ws,)),
    }


def _tree_to_brackets(text):
    """Flatten the indented playground_prompt tree onto a single line so it fits
    in one CSV cell, using nested braces to keep the parent/child structure.
    The depth-0 section headers ([Active]/[Orphaned]) stay as bare inline labels;
    only blocks at depth >= 1 that actually have children get wrapped in { }.
    Indentation is one space per level (matches smart_delta_engine.build_tree)."""
    lines = [(len(l) - len(l.lstrip(" ")), l.strip()) for l in text.split("\n") if l.strip()]
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


def _cursor_csv(cur):
    """Render an executed cursor's rows as a CSV string. JSON columns come out
    as raw JSON text, and cells are flattened to one line."""
    cols = [d[0] for d in cur.description]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for row in cur:
        w.writerow([_csv_value(c, v) for c, v in zip(cols, row.values())])
    return buf.getvalue()


def export_zip_bytes(workspace_id=None):
    """An in-memory zip of one CSV per table, scoped to the workspace. Purely a
    read. The Export button streams it, and a reset saves it before it clears."""
    buf = io.BytesIO()
    with _get_pool().connection() as con, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for table, (sql, params) in _workspace_export_queries(_ws(workspace_id)).items():
            z.writestr(f"{table}.csv", _cursor_csv(con.execute(sql, params)))
    return buf.getvalue()


# --------------------------------------------------------------------------
# row shaping
# --------------------------------------------------------------------------
def _student_state_row(r):
    return {
        "studentID": r["studentid"],
        "display_id": r["display_id"],
        "classCode": r["classcode"],
        "run_count": r["run_count"],
        "event_count": r["event_count"],
        "runs": _json(r["runs"]),
        "episodes": _json(r["episodes"]),
        "playground_prompt": r["playground_prompt"],
        "playground_time": r["playground_time"],
        "last_event_id": r["last_event_id"],
        "last_event_time": r["last_event_time"],
        "updated_at": r["updated_at"],
    }


def _trigger_row(r):
    return {
        "id": r["id"],
        "studentID": r["studentid"],
        "trigger_type": r["trigger_type"],
        "started_at": r["started_at"],
        "last_seen_at": r["last_seen_at"],
        "resolved_at": r["resolved_at"],
        "acknowledged": r["acknowledged"],
        "detail": _json(r["detail"]),
    }


# ==========================================================================
# Queries the API layer calls: reads of the materialized state plus the small
# writes it owns (roster, acks, presence/picked toggles, notes).
# ==========================================================================
def list_student_states(students=None, class_code=None, workspace_id=None):
    """Materialized state rows. student_state is shared (per student); passing
    workspace_id restricts the result to the students on that workspace's roster,
    which is how the API keeps one board from seeing another's students."""
    sql = "SELECT * FROM student_state"
    clauses, params = [], []
    if students:
        clauses.append("studentID = ANY(%s)")
        params.append([canon_id(s) for s in students])
    if class_code:
        clauses.append("classCode = %s")
        params.append(class_code)
    if workspace_id is not None:
        clauses.append(
            "studentID IN (SELECT studentID FROM tracked_student WHERE workspace_id = %s)"
        )
        params.append(workspace_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return [_student_state_row(r) for r in _query(sql, params)]


# trigger_event is shared (daemon-written per student); the intervention feed is
# scoped to a workspace's roster and acknowledgement is per-workspace via
# trigger_ack. Both queries compute `acknowledged` from that overlay, not from
# trigger_event.acknowledged, which is the daemon's global re-alert flag.
_TRIG_COLS = (
    "te.id, te.studentID, te.trigger_type, te.started_at, te.last_seen_at, "
    "te.resolved_at, te.detail"
)


def triggers_feed(cutoff, limit=100, workspace_id=None, since=None):
    """The intervention feed: triggers not dismissed by this workspace, either
    still open or resolved at/after `cutoff`, newest first. Passing workspace_id
    also restricts to that board's roster (the routes always do); with None the
    feed spans all students (dismissals still resolve against the default
    workspace, which is what the daemon/tests use)."""
    ack_ws = _ws(workspace_id)
    params = [ack_ws]
    roster = ""
    if workspace_id is not None:
        roster = (
            "AND te.studentID IN (SELECT studentID FROM tracked_student WHERE workspace_id = %s) "
        )
        params.append(workspace_id)
    after = ""
    if since is not None:
        # A reset hides earlier alerts, except one still open: that is the
        # student's current state (e.g. idle right now), not history.
        after = "AND (te.resolved_at IS NULL OR te.started_at >= %s) "
        params.append(since)
    params += [cutoff, limit]
    rows = _query(
        f"SELECT {_TRIG_COLS}, FALSE AS acknowledged FROM trigger_event te "
        "LEFT JOIN trigger_ack ta ON ta.trigger_id = te.id AND ta.workspace_id = %s "
        f"WHERE ta.trigger_id IS NULL {roster}{after}"
        "AND (te.resolved_at IS NULL OR te.resolved_at >= %s) "
        "ORDER BY te.started_at DESC LIMIT %s",
        params,
    )
    return [_trigger_row(r) for r in rows]


def trigger_history(sid, limit=100, workspace_id=None, since=None):
    """Every trigger ever fired for one student, newest first -- open, resolved,
    and dismissed alike -- with this workspace's ack status. The detail modal
    renders it as the trigger-history grid; the feed uses it for each alert's
    previous trigger. Case-insensitive via the canonical key."""
    params = [_ws(workspace_id), canon_id(sid)]
    after = ""
    if since is not None:
        after = "AND te.started_at >= %s "
        params.append(since)
    rows = _query(
        f"SELECT {_TRIG_COLS}, (ta.trigger_id IS NOT NULL) AS acknowledged "
        "FROM trigger_event te "
        "LEFT JOIN trigger_ack ta ON ta.trigger_id = te.id AND ta.workspace_id = %s "
        f"WHERE te.studentID = %s {after}"
        "ORDER BY te.started_at DESC, te.id DESC LIMIT %s",
        (*params, limit),
    )
    return [_trigger_row(r) for r in rows]


def ack_by_id(tid, workspace_id=None):
    n = _execute(
        "INSERT INTO trigger_ack (workspace_id, trigger_id, ts) VALUES (%s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (_ws(workspace_id), tid, now()),
    )
    # Keep the shared trigger_event.acknowledged flag in sync: the daemon's
    # re-alert logic (a global, per-student behavior) reads it to decide when an
    # acked-but-still-open alert should rotate into a fresh row.
    _execute("UPDATE trigger_event SET acknowledged = true WHERE id = %s", (tid,))
    return n


def ack_by_student(sid, workspace_id=None):
    """Dismiss (for this workspace) every trigger currently fired for a student."""
    sid = canon_id(sid)
    n = _execute(
        "INSERT INTO trigger_ack (workspace_id, trigger_id, ts) "
        "SELECT %s, id, %s FROM trigger_event WHERE studentID = %s "
        "ON CONFLICT DO NOTHING",
        (_ws(workspace_id), now(), sid),
    )
    _execute(
        "UPDATE trigger_event SET acknowledged = true WHERE studentID = %s AND NOT acknowledged",
        (sid,),
    )
    return n


def tracked_list(workspace_id=None):
    # A single LEFT JOIN rather than a roster query followed by per-student
    # lookups: has_data is just whether a matching student_state row exists.
    # tracked_student is scoped to the workspace; student_state is shared and keyed
    # UNIQUE on studentID, so the join is strictly 1:1.
    rows = _query(
        "SELECT t.studentID, t.backfilled, t.present, t.picked, t.picked_at, "
        "       s.display_id, (s.studentID IS NOT NULL) AS has_data "
        "FROM tracked_student t "
        "LEFT JOIN student_state s ON s.studentID = t.studentID "
        "WHERE t.workspace_id = %s "
        "ORDER BY t.studentID",
        (_ws(workspace_id),),
    )
    return [
        {
            "studentID": r["studentid"],  # canonical key
            "display": r["display_id"] or r["studentid"],  # most-recent casing for the UI
            "backfilled": r["backfilled"],
            "has_data": r["has_data"],
            "present": r["present"],
            "picked": r["picked"],
            "picked_at": r["picked_at"],
        }
        for r in rows
    ]


def set_presence(sid, present, workspace_id=None):
    """Researcher toggle for whether the student is physically in the room. Scoped
    to the workspace, so one board's presence never affects another's."""
    _execute(
        "UPDATE tracked_student SET present = %s WHERE workspace_id = %s AND studentID = %s",
        (present, _ws(workspace_id), canon_id(sid)),
    )


def set_picked(sid, picked, source="roster", trigger_id=None, trigger_type=None, workspace_id=None):
    """Researcher toggle for whether the student has been picked/interviewed this
    session, scoped to the workspace. Marking stamps picked_at; unmarking clears
    it. Either way it also appends a pick_event row, so the full pick/unpick
    history is timestamped for later analysis (picked_at only holds the latest
    state; pick_event is the log).

    Provenance rides only on the log row: `source` is 'roster' (student card) or
    'intervention' (alert card), and trigger_id/trigger_type name the alert an
    intervention pick was clicked from (both None for roster picks)."""
    wsid = _ws(workspace_id)
    sid = canon_id(sid)
    ts = now()
    with write_txn() as con:
        con.execute(
            "UPDATE tracked_student SET picked = %s, picked_at = %s "
            "WHERE workspace_id = %s AND studentID = %s",
            (picked, ts if picked else None, wsid, sid),
        )
        con.execute(
            "INSERT INTO pick_event "
            "(workspace_id, studentID, picked, ts, source, trigger_id, trigger_type) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (wsid, sid, picked, ts, source, trigger_id, trigger_type),
        )


def add_note(student_id, text, trigger_id=None, trigger_type=None, workspace_id=None):
    """Record one note for a student in a workspace. Pass trigger_id/trigger_type
    to link it to the alert it was written from; leave both None for a free-standing
    manual note. Returns the new row as a dict."""
    wsid = _ws(workspace_id)
    student_id = canon_id(student_id)
    ts = now()
    with write_txn() as con:
        cur = con.execute(
            "INSERT INTO note "
            "(workspace_id, studentID, ts, text, trigger_id, trigger_type, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (wsid, student_id, ts, text, trigger_id, trigger_type, ts),
        )
        nid = cur.fetchone()["id"]
    return {
        "id": nid,
        "studentID": student_id,
        "ts": ts,
        "text": text,
        "trigger_id": trigger_id,
        "trigger_type": trigger_type,
        "created_at": ts,
    }


def list_notes(student_id, workspace_id=None):
    """A workspace's notes for a student, in chronological order."""
    rows = _query(
        "SELECT id, studentID, ts, text, trigger_id, trigger_type, created_at "
        "FROM note WHERE workspace_id = %s AND studentID = %s ORDER BY ts, id",
        (_ws(workspace_id), canon_id(student_id)),
    )
    # Explicit keys, not dict(r): Postgres returns lower-cased column names, and
    # this dict is serialized straight to API JSON where the UI expects studentID.
    return [
        {
            "id": r["id"],
            "studentID": r["studentid"],
            "ts": r["ts"],
            "text": r["text"],
            "trigger_id": r["trigger_id"],
            "trigger_type": r["trigger_type"],
            "created_at": r["created_at"],
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
        "VALUES (%s, %s, %s, %s, %s)",
        (student_id, kind, from_value, to_value, now()),
    )


def record_outbox(op, payload, error, workspace_id=None):
    """Park a researcher input whose primary write failed, verbatim, so it can
    be replayed by hand later. `payload` is the original request body (already a
    JSON string, or None)."""
    _execute(
        "INSERT INTO outbox (workspace_id, op, payload, error, created_at) VALUES (%s, %s, %s, %s, %s)",
        (_ws(workspace_id), op, payload, error, now()),
    )


def list_outbox(limit=200, workspace_id=None):
    """A workspace's parked failed inputs, newest first."""
    rows = _query(
        "SELECT id, op, payload, error, created_at FROM outbox "
        "WHERE workspace_id = %s ORDER BY id DESC LIMIT %s",
        (_ws(workspace_id), limit),
    )
    return [dict(r) for r in rows]


def list_switches(limit=100, unacked_only=False, workspace_id=None, since=None):
    """Recent switches, newest first. switch_event is shared (daemon-detected per
    student); passing workspace_id scopes it to the students that board tracks
    (the route always does). `unacked_only` keeps just the ones not yet dismissed."""
    clauses, params = [], []
    if workspace_id is not None:
        clauses.append(
            "studentID IN (SELECT studentID FROM tracked_student WHERE workspace_id = %s)"
        )
        params.append(workspace_id)
    if unacked_only:
        clauses.append("NOT acknowledged")
    if since is not None:
        clauses.append("ts >= %s")
        params.append(since)
    where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
    rows = _query(
        "SELECT id, studentID, kind, from_value, to_value, ts, acknowledged "
        f"FROM switch_event {where}ORDER BY ts DESC, id DESC LIMIT %s",
        (*params, limit),
    )
    # Explicit keys (see list_notes): preserve the studentID casing the UI expects.
    return [
        {
            "id": r["id"],
            "studentID": r["studentid"],
            "kind": r["kind"],
            "from_value": r["from_value"],
            "to_value": r["to_value"],
            "ts": r["ts"],
            "acknowledged": r["acknowledged"],
        }
        for r in rows
    ]


def ack_switch(switch_id):
    """Dismiss one switch by id so it stops showing as new."""
    return _execute("UPDATE switch_event SET acknowledged = true WHERE id = %s", (switch_id,))


def tracked_add(sid, workspace_id=None):
    """Add a student to a workspace's roster (no-op if already there). The daemon
    notices the new, not-yet-backfilled row on its next tick and pulls history."""
    _execute(
        "INSERT INTO tracked_student (workspace_id, studentID, backfilled, created_at) "
        "VALUES (%s, %s, false, %s) ON CONFLICT (workspace_id, studentID) DO NOTHING",
        (_ws(workspace_id), canon_id(sid), now()),
    )


def mark_workspace_for_backfill(workspace_id=None):
    """Ask the daemon to backfill every student on this workspace's roster again.
    Used when a paused board resumes: while it was paused its students weren't
    fetched, but the shared cursor moved on if another board was live."""
    _execute(
        "UPDATE tracked_student SET backfilled = false WHERE workspace_id = %s",
        (_ws(workspace_id),),
    )


def mark_backfilled(sid):
    # Backfill pulls a student's shared history once, so mark every workspace's
    # roster row for that student (the daemon ingests the union, per student).
    _execute("UPDATE tracked_student SET backfilled = true WHERE studentID = %s", (canon_id(sid),))


def tracked_remove(sid, workspace_id=None):
    """Untrack a student from one workspace's roster. The shared raw events and
    derived state are only purged once NO workspace tracks the student any more --
    another board watching the same student keeps their mirror alive."""
    wsid = _ws(workspace_id)
    sid = canon_id(sid)
    with write_txn() as con:
        con.execute(
            "DELETE FROM tracked_student WHERE workspace_id = %s AND studentID = %s",
            (wsid, sid),
        )
        still_tracked = con.execute(
            "SELECT 1 FROM tracked_student WHERE studentID = %s LIMIT 1", (sid,)
        ).fetchone()
        if still_tracked:
            return
        # No workspace tracks them any more -- purge the shared mirror + derived state.
        _purge_student(con, sid)


def _purge_student(con, sid):
    """Delete a student's mirrored events and everything derived from them, in `con`'s
    transaction. vex_log keeps the source's raw casing, so it matches case-insensitively."""
    msg_ids = [
        r["from_message_id"]
        for r in con.execute(
            "DELETE FROM vex_log WHERE lower(studentID) = %s RETURNING from_message_id", (sid,)
        )
    ]
    con.execute("DELETE FROM message WHERE id = ANY(%s)", (msg_ids,))
    con.execute("DELETE FROM student_state WHERE studentID = %s", (sid,))
    con.execute("DELETE FROM trigger_event WHERE studentID = %s", (sid,))
    # Everything else derived from their events goes too, or a re-add would
    # mix these stale goal runs and switches into the rebuilt ones.
    con.execute("DELETE FROM goal_profile WHERE studentID = %s", (sid,))
    con.execute("DELETE FROM switch_event WHERE studentID = %s", (sid,))


def forget_student(sid):
    """Drop a student's mirror and models and backfill them again from the source: ATLAS
    deleted some of a ZANY student's records, so only what its store still has comes back.
    The roster, presence, picks and notes stay, being the researcher's own."""
    sid = canon_id(sid)
    with write_txn() as con:
        _purge_student(con, sid)
        con.execute("UPDATE tracked_student SET backfilled = false WHERE studentID = %s", (sid,))


ZANY_LIKE = "zany:%"  # a parameter, as a literal % in a query with parameters must be %%


def forget_all_zany():
    """Drop every ZANY student's mirror and models, to backfill them from ATLAS's store: the
    daemon does this on starting, so nothing ATLAS deleted while it was down survives."""
    with write_txn() as con:
        sids = {
            r["sid"]
            for r in con.execute(
                "SELECT lower(studentID) AS sid FROM vex_log WHERE zany_seq IS NOT NULL "
                "UNION SELECT studentID FROM student_state WHERE studentID LIKE %s "
                "UNION SELECT studentID FROM tracked_student WHERE studentID LIKE %s",
                (ZANY_LIKE, ZANY_LIKE),
            ).fetchall()
        }
        for sid in sids:
            _purge_student(con, sid)
        con.execute(
            "UPDATE tracked_student SET backfilled = false WHERE studentID LIKE %s", (ZANY_LIKE,)
        )


# ==========================================================================
# Pipeline queries: the ingest cursor (how far the poller has consumed)
# ==========================================================================
def get_or_create_cursor(name):
    rows = _query("SELECT * FROM ingest_cursor WHERE name = %s", (name,))
    if not rows:
        _execute(
            "INSERT INTO ingest_cursor (name, last_source_id, last_event_time, updated_at) "
            "VALUES (%s, 0, NULL, %s)",
            (name, now()),
        )
        rows = _query("SELECT * FROM ingest_cursor WHERE name = %s", (name,))
    r = rows[0]
    return {
        "name": r["name"],
        "last_source_id": r["last_source_id"] or 0,
        "last_event_time": r["last_event_time"],
    }


def save_cursor(name, last_event_time, last_source_id):
    _execute(
        "UPDATE ingest_cursor SET last_event_time = %s, last_source_id = %s, updated_at = %s "
        "WHERE name = %s",
        (last_event_time, last_source_id, now(), name),
    )


# ==========================================================================
# Pipeline queries: the append-only raw event log (written only by the poller)
# ==========================================================================
def zany_row_exists(seq):
    return bool(_query("SELECT 1 FROM vex_log WHERE zany_seq = %s LIMIT 1", (seq,)))


def log_exists(source_event_id):
    if source_event_id is None:
        return False
    return bool(
        _query("SELECT 1 FROM vex_log WHERE source_event_id = %s LIMIT 1", (source_event_id,))
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
                "VALUES (%s, '', '', %s, %s) RETURNING id",
                (
                    "zany" if norm.get("zany_seq") is not None else "pipeline",
                    norm["raw_message"],
                    norm["event_time"] or now(),
                ),
            )
            message_id = cur.fetchone()["id"]
            con.execute(
                "INSERT INTO vex_log "
                "(from_message_id, classCode, eventType, studentID, project, raw_message, "
                " event_time, source_event_id, zany_seq) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    message_id,
                    norm["classCode"],
                    norm["eventType"],
                    norm["studentID"],
                    norm["project"],
                    norm["raw_message"],
                    norm["event_time"],
                    norm["source_event_id"],
                    norm.get("zany_seq"),
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
    where, params = "lower(v.studentID) = %s", [canon_id(sid)]
    if since is not None:
        # Stored datetimes are fixed-width strings, so a lexical >= is chronological.
        where += " AND COALESCE(v.event_time, m.received_at) >= %s"
        params.append(since)

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
        f"WHERE {where} {order_by} LIMIT %s",
        (*params, limit),
    )
    out = []
    for r in reversed(rows):
        out.append(
            {
                "studentID": r["studentid"],
                "eventType": r["eventtype"],
                "classCode": r["classcode"],
                "project": r["project"],
                "raw_message": r["raw_message"],
                "event_time": r["event_time"],
                "received_at": r["received_at"],
                "source_event_id": r["source_event_id"],
            }
        )
    return out


# ==========================================================================
# Pipeline queries: the materialized student_state view (daemon writes it,
# the API reads it)
# ==========================================================================
_STATE_JSON_FIELDS = ("runs", "episodes")


def upsert_student_state(student_id, defaults):
    cols = {"studentID": student_id, "updated_at": now()}
    for k, v in defaults.items():
        cols[k] = json.dumps(v) if k in _STATE_JSON_FIELDS else v
    keys = list(cols.keys())
    updates = ", ".join(f"{k}=excluded.{k}" for k in keys if k != "studentID")
    sql = (
        f"INSERT INTO student_state ({', '.join(keys)}) "
        f"VALUES ({', '.join(['%s'] * len(keys))}) "
        f"ON CONFLICT(studentID) DO UPDATE SET {updates}"
    )
    _execute(sql, tuple(cols[k] for k in keys))


# ==========================================================================
# Goal profiles: one row per profiled run, shared per student (like student_state).
# ==========================================================================
def upsert_goal_profile(student_id, run_index, result, session=""):
    """Store one run's goal_strategy result dict. `result` is the full envelope
    (index, playground, status, profile, diagnostics, ...); we keep the whole
    thing as JSON and lift a few columns out for querying/export. `session` is
    the daemon session run_index counts within (see workers.session_key)."""
    sql = (
        "INSERT INTO goal_profile "
        "(studentID, session, run_index, playground, status, ts, profile, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT(studentID, session, run_index) DO UPDATE SET "
        "playground=excluded.playground, status=excluded.status, ts=excluded.ts, "
        "profile=excluded.profile, updated_at=excluded.updated_at"
    )
    _execute(
        sql,
        (
            canon_id(student_id),
            session or "",
            int(run_index),
            result.get("playground"),
            result.get("status"),
            result.get("ts"),
            json.dumps(result),
            now(),
        ),
    )


_CURRENT = object()  # sentinel: "the daemon's current session"


def current_session():
    """The session key the daemon published at startup, or None when no daemon
    has (tests, a fresh database)."""
    return get_meta(SESSION_META_KEY)


def list_goal_profiles(student_id, session=_CURRENT, since=None):
    """A student's stored goal profiles, oldest run first, as the full result
    dicts (the drill-down joins them to runs by run_index). By default only the
    daemon's current session, since run_index restarts every session; pass
    session=None for every session. `since` (a UTC datetime) drops runs from
    before it, e.g. a board reset."""
    if session is _CURRENT:
        session = current_session()
    where, params = ["studentID = %s"], [canon_id(student_id)]
    if session is not None:
        where.append("session = %s")
        params.append(session)
    if since is not None:
        where.append("ts >= %s")
        params.append(since.timestamp())
    rows = _query(
        f"SELECT profile FROM goal_profile WHERE {' AND '.join(where)} ORDER BY session, run_index",
        params,
    )
    return [json.loads(r["profile"]) for r in rows if r.get("profile")]


# ==========================================================================
# Pipeline queries: trigger_event lifecycle (open / touch / resolve)
# ==========================================================================
def all_student_states():
    """A trimmed projection of every student_state row, just the columns the
    sustained-trigger sweep (inactive) needs."""
    rows = _query("SELECT studentID, last_event_time FROM student_state")
    return [{"studentID": r["studentid"], "last_event_time": r["last_event_time"]} for r in rows]


def current_open_trigger(student_id, ttype):
    rows = _query(
        "SELECT * FROM trigger_event "
        "WHERE studentID = %s AND trigger_type = %s AND resolved_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1",
        (student_id, ttype),
    )
    return _trigger_row(rows[0]) if rows else None


def open_triggers_by_student(ttype):
    """Every currently-open (unresolved) trigger of one type, keyed by studentID.
    One query for the whole cohort -- the sustained-trigger sweep uses this
    instead of a per-student current_open_trigger() lookup. A student can only
    have one open row per type (the sweep maintains that), so last-wins on the
    off chance of a duplicate is harmless."""
    rows = _query(
        "SELECT * FROM trigger_event WHERE trigger_type = %s AND resolved_at IS NULL",
        (ttype,),
    )
    return {r["studentid"]: _trigger_row(r) for r in rows}


def apply_sustained_sweep(creates, resolve_ids, touches):
    """Flush one sustained-trigger sweep atomically: a batch of new rows, a batch
    of resolves (by id), and a batch of last_seen_at touches (by id) -- each an
    executemany, so the whole sweep is ~3 statements regardless of cohort size
    instead of a query per student. Args:
      creates:    [(student_id, trigger_type, started_at, last_seen_at, detail)]
      resolve_ids:[(trigger_id, resolved_at)]
      touches:    [(trigger_id, last_seen_at, detail)]
    All datetimes are python datetimes / detail is a dict; this does the db
    encoding so callers stay in app types."""
    if not (creates or resolve_ids or touches):
        return
    with write_txn() as con:
        if creates:
            con.cursor().executemany(
                "INSERT INTO trigger_event "
                "(studentID, trigger_type, started_at, last_seen_at, resolved_at, "
                " acknowledged, detail, created_at) VALUES (%s, %s, %s, %s, NULL, false, %s, %s)",
                [(sid, tt, st, ls, json.dumps(d), now()) for (sid, tt, st, ls, d) in creates],
            )
        if resolve_ids:
            con.cursor().executemany(
                "UPDATE trigger_event SET resolved_at = %s WHERE id = %s",
                [(ra, tid) for (tid, ra) in resolve_ids],
            )
        if touches:
            con.cursor().executemany(
                "UPDATE trigger_event SET last_seen_at = %s, detail = %s WHERE id = %s",
                [(ls, json.dumps(d), tid) for (tid, ls, d) in touches],
            )


def create_trigger(student_id, trigger_type, started_at, last_seen_at, resolved_at, detail):
    _execute(
        "INSERT INTO trigger_event "
        "(studentID, trigger_type, started_at, last_seen_at, resolved_at, "
        " acknowledged, detail, created_at) VALUES (%s, %s, %s, %s, %s, false, %s, %s)",
        (
            student_id,
            trigger_type,
            started_at,
            last_seen_at,
            resolved_at,
            json.dumps(detail),
            now(),
        ),
    )


def fired_indices(student_id, trigger_type, session=None):
    """Run indices that already produced a momentary trigger of this type. A worker
    loads these once on cold start to seed its in-memory dedupe, so a re-backfill
    never re-fires an old run and the trigger sweep needn't re-scan history. Run
    indices restart every daemon session, so pass `session` to count only that
    session's alerts (else an old session's run 3 would silence this one's)."""
    sql = (
        "SELECT (detail::jsonb ->> 'run_index')::int AS i FROM trigger_event "
        "WHERE studentID = %s AND trigger_type = %s"
    )
    params = [student_id, trigger_type]
    if session is not None:
        sql += " AND COALESCE(detail::jsonb ->> 'session', '') = %s"
        params.append(session)
    rows = _query(sql, params)
    return {r["i"] for r in rows if r["i"] is not None}
