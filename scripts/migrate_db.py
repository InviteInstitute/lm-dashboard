"""
One-shot, idempotent migration from the old Django SQLite layout to the lean one.

  python scripts/migrate_db.py [path/to/db.sqlite3]

1. Renames the six `rabbitmq_*` tables to clean names (data + indexes preserved).
2. Drops the leftover Django/legacy tables (auth_*, django_*, accounts_*, ...).
3. VACUUMs -- the file is ~99% free pages from deleted data, so it shrinks hugely.

Safe to run more than once. Back up first (the app expects db.backup.sqlite3 to
already exist from the restructure, but `cp db.sqlite3 db.bak.sqlite3` never hurts).
"""
import os
import sqlite3
import sys

RENAMES = {
    "rabbitmq_message": "message",
    "rabbitmq_vexactivitylog": "vex_log",
    "rabbitmq_ingestcursor": "ingest_cursor",
    "rabbitmq_studentstate": "student_state",
    "rabbitmq_trackedstudent": "tracked_student",
    "rabbitmq_triggerevent": "trigger_event",
}
CLEAN_TABLES = set(RENAMES.values())
# Internal SQLite tables we must never touch.
KEEP_INTERNAL = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}


def _tables(cur):
    return {
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def main(path="db.sqlite3"):
    if not os.path.exists(path):
        sys.exit(f"no such DB: {path}")
    before = os.path.getsize(path) / 1e6
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")
    tables = _tables(cur)

    # 1. rename rabbitmq_* -> clean
    for old, new in RENAMES.items():
        if old in tables and new not in tables:
            cur.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
            print(f"renamed {old} -> {new}")
        elif new in tables:
            print(f"skip {old}: {new} already exists")
    con.commit()

    # 2. drop everything that isn't one of our clean tables or sqlite-internal
    tables = _tables(cur)
    for t in sorted(tables - CLEAN_TABLES - KEEP_INTERNAL):
        cur.execute(f'DROP TABLE IF EXISTS "{t}"')
        print(f"dropped leftover table {t}")
    con.commit()

    # 3. reclaim the free pages
    print("vacuuming...")
    cur.execute("VACUUM")
    con.commit()

    # report
    print("\nclean tables:")
    for t in sorted(CLEAN_TABLES):
        try:
            n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            print(f"  {t}: {n} rows")
        except sqlite3.OperationalError:
            print(f"  {t}: MISSING")
    con.close()
    after = os.path.getsize(path) / 1e6
    print(f"\nsize: {before:.1f} MB -> {after:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "db.sqlite3")
