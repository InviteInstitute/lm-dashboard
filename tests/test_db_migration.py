"""init_db's one-time conversion of a database from before the native types, where
timestamps were UTC text and flags were 0/1 smallints."""

from datetime import UTC, datetime

from app import db


def _make_legacy():
    """Turn the test schema back into the old shape: every timestamptz column to
    naive UTC text, every boolean to a 0/1 smallint."""
    with db.write_txn() as con:
        cols = con.execute(
            "SELECT table_name, column_name, data_type, column_default "
            "FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND data_type IN ('timestamp with time zone', 'boolean')"
        ).fetchall()
        for c in cols:
            t, n = c["table_name"], c["column_name"]
            if c["data_type"] == "boolean":
                con.execute(f"ALTER TABLE {t} ALTER {n} DROP DEFAULT")
                con.execute(f"ALTER TABLE {t} ALTER {n} TYPE smallint USING {n}::int")
                if c["column_default"]:
                    default = 1 if c["column_default"] == "true" else 0
                    con.execute(f"ALTER TABLE {t} ALTER {n} SET DEFAULT {default}")
            else:
                con.execute(
                    f"ALTER TABLE {t} ALTER {n} TYPE text USING "
                    f"to_char({n} AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')"
                )


def test_init_db_converts_text_timestamps_and_smallint_flags():
    _make_legacy()
    ws = db.default_workspace_id()
    db._execute(
        "INSERT INTO tracked_student (workspace_id, studentID, backfilled, present, picked, "
        "picked_at, created_at) VALUES (%s, 'cobra3', 1, 0, 1, "
        "'2026-11-25 09:40:38.112132', '2026-11-25 09:00:00.000000')",
        (ws,),
    )
    db._execute(
        "INSERT INTO workspace_setting (workspace_id, key, value) "
        "VALUES (%s, 'reset_at', '2026-11-25 10:00:00.000000')",
        (ws,),
    )

    db.init_db()

    row = db.tracked_list()[0]
    assert (row["backfilled"], row["present"], row["picked"]) == (True, False, True)
    assert row["picked_at"] == datetime(2026, 11, 25, 9, 40, 38, 112132, tzinfo=UTC)
    assert db.reset_since(ws) == datetime(2026, 11, 25, 10, tzinfo=UTC)
    db.tracked_add("viper1")  # the defaults came back as booleans
    assert [r["present"] for r in db.tracked_list()] == [False, True]
    db.init_db()  # and a second run leaves the converted database alone
