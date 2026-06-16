"""
End-of-day data export: dump the local SQLite database to CSV files.

    python scripts/export_csv.py                      # → exports/<YYYY-MM-DD_HHMM>/
    python scripts/export_csv.py --out data/today     # choose the output folder
    python scripts/export_csv.py --tables student_state,trigger_event
    python scripts/export_csv.py --db /path/to/db.sqlite3

Writes one CSV per table. JSON columns (runs / episodes / detail) are written as
raw JSON text; load them in pandas with json.loads. This script is READ-ONLY; it
never modifies the database. Delegates to db.export_csv so it stays in sync with
the API's Export button.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser(
        description="Dump the SQLite DB to CSV (one file per table + all_data.csv)."
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
    tables = [t.strip() for t in args.tables.split(",") if t.strip()] if args.tables else None

    out_dir, written = db.export_csv(out_dir, tables=tables, db_path=args.db)
    print(f"exported → {out_dir}/")
    for name, n in sorted(written.items()):
        fname = name if name.endswith(".csv") else f"{name}.csv"
        print(f"  {fname:24} {n:8} rows")


if __name__ == "__main__":
    main()
