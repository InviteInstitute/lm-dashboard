"""
End-of-day data export: dump the local SQLite database to CSV files.

    python scripts/export_csv.py                      # → exports/<YYYY-MM-DD_HHMM>/<table>.csv
    python scripts/export_csv.py --out data/today     # choose the output folder
    python scripts/export_csv.py --tables student_state,trigger_event
    python scripts/export_csv.py --db /path/to/db.sqlite3

One CSV per table, with a header row. JSON columns (runs / episodes / detail) are
written as raw JSON text — load them in pandas with `json.loads`, or treat them as
text in a spreadsheet. This script is READ-ONLY; it never modifies the database.
"""
import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime

# SQLite bookkeeping tables we never export.
INTERNAL = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}


def list_tables(cur):
    rows = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if r[0] not in INTERNAL]


def export_table(con, table, out_dir):
    cur = con.execute(f'SELECT * FROM "{table}"')
    cols = [d[0] for d in cur.description]
    path = os.path.join(out_dir, f"{table}.csv")
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for row in cur:
            writer.writerow(row)
            n += 1
    return path, n


def main():
    ap = argparse.ArgumentParser(
        description="Dump the SQLite DB to CSV files (one per table)."
    )
    ap.add_argument("--db", default="db.sqlite3",
                    help="SQLite file to export (default: db.sqlite3)")
    ap.add_argument("--out", default=None,
                    help="output directory (default: exports/<timestamp>)")
    ap.add_argument("--tables", default=None,
                    help="comma-separated subset of tables (default: all)")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"no such DB: {args.db}")

    out_dir = args.out or os.path.join("exports", datetime.now().strftime("%Y-%m-%d_%H%M"))
    os.makedirs(out_dir, exist_ok=True)

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    tables = (
        [t.strip() for t in args.tables.split(",") if t.strip()]
        if args.tables else list_tables(cur)
    )

    print(f"exporting {len(tables)} table(s) from {args.db} → {out_dir}/")
    total = 0
    for t in tables:
        try:
            path, n = export_table(con, t, out_dir)
            total += n
            print(f"  {t:18} {n:8} rows → {os.path.basename(path)}")
        except sqlite3.OperationalError as e:
            print(f"  {t:18} SKIP ({e})")
    con.close()
    print(f"done: {total} rows across {len(tables)} file(s) in {out_dir}/")


if __name__ == "__main__":
    main()
