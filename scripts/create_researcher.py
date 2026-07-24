#!/usr/bin/env python
"""Create a researcher login, or reset an existing one's password.

    python scripts/create_researcher.py <username>              # prompts for the password
    python scripts/create_researcher.py <username> --password s3cret

Usernames are case-insensitive (folded to lower case). Re-running for an existing
username just updates the password.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth, config, db  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--password", default=None,
                    help="the password (omit to be prompted, which is safer)")
    opts = ap.parse_args(argv)
    if not config.DATABASE_URL:
        ap.error("DATABASE_URL is not set (put it in .env.mirror)")

    password = opts.password or getpass.getpass("Password: ")
    if not password:
        ap.error("empty password")

    db.init_db()
    rid = db.upsert_researcher(opts.username, auth.hash_password(password))
    print(f"researcher '{opts.username.strip().lower()}' ready (id={rid}).")


if __name__ == "__main__":
    main()
