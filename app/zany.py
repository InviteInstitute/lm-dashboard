"""ZANY's study logs as a second source, beside Reflecks.

ZANY sends its learner logs to ATLAS-invite (zany.inviteai.org), which keeps only the records a
participant's consent allows, in a PostgreSQL store of its own. lm-dashboard reads that store
read-only (role lmdash_reader, table log_record only) and listens for the two notifications ATLAS
sends when the store commits: `zany_records` when records are kept, `zany_forgotten` when some are
deleted. The records have Reflecks' fields (VEXcode VR's log format), so the rest of the pipeline
treats them as it treats Reflecks events.

A ZANY student is keyed `zany:<study>:<participant ID>` (STUDY-0001 is ATLAS's name for the
study), so they never collide with a Reflecks student ID. A store row is keyed by its `seq`, which
counts up as ATLAS stores rows; a record's own `id` only counts within one page session.

Reading ZANY's logs needs the research login: lm-dashboard signs in to ATLAS with what a person
typed, asks whether the account is a researcher, and signs out (`researcher_login`).
"""

import json
import logging
import time

import psycopg
import requests

from app import config

log = logging.getLogger(__name__)

PREFIX = "zany:"
KEPT = "zany_records"
FORGOTTEN = "zany_forgotten"
PAGE = 1000


def enabled():
    """Whether this deployment can reach ZANY's log store at all."""
    return bool(config.ZANY_LOG_DSN)


def key(study, participant_id):
    """A ZANY student's ID in lm-dashboard (canon_id folds its case, as for Reflecks IDs)."""
    return f"{PREFIX}{study}:{participant_id}"


def is_zany(student_id):
    return (student_id or "").lower().startswith(PREFIX)


def split(student_id):
    """(study, participant ID) of a ZANY key, in the case the key was written in."""
    study, _, participant = student_id[len(PREFIX) :].partition(":")
    return study, participant


def connect():
    return psycopg.connect(config.ZANY_LOG_DSN, autocommit=True)


def _event(seq, study, stored_at, record):
    """A store row as the pipeline's normalized event (poller._normalize's shape). The time is
    when ATLAS stored it, the server's clock, as Reflecks' received_at is."""
    return {
        "studentID": key(study, record.get("studentID") or ""),
        "classCode": record.get("classCode") or "",
        "eventType": record.get("eventType") or "",
        "project": record.get("project") or "",
        "raw_message": record.get("raw_message") or "{}",
        "source_event_id": None,
        "zany_seq": seq,
        "event_time": stored_at,
    }


def rows_after(con, seq, limit=PAGE):
    """Every study row stored after `seq`, oldest first."""
    return con.execute(
        "SELECT seq, research_study, stored_at, record FROM log_record WHERE seq > %s ORDER BY seq LIMIT %s",
        (seq, limit),
    ).fetchall()


def student_rows(con, student_id, since=None):
    """One ZANY student's rows, oldest first, optionally only those stored from `since` on.
    ponytail: matches the participant ID inside the record (no index on it); fine for a class,
    add an expression index on lower(record->>'studentID') if backfills slow down."""
    study, participant = split(student_id)
    sql = (
        "SELECT seq, research_study, stored_at, record FROM log_record"
        " WHERE lower(research_study) = lower(%s) AND lower(record->>'studentID') = lower(%s)"
    )
    params = [study, participant]
    if since is not None:
        sql += " AND stored_at >= %s"
        params.append(since)
    return con.execute(sql + " ORDER BY seq", params).fetchall()


def studies():
    """The studies with records in the store, newest activity first: ATLAS's name for each, the
    study code students type, how many participants have records, and when the last came in."""
    with connect() as con:
        rows = con.execute(
            "SELECT research_study, max(record->>'classCode'), count(DISTINCT record->>'studentID'),"
            " max(stored_at) FROM log_record GROUP BY research_study ORDER BY max(stored_at) DESC"
        ).fetchall()
    return [
        {"study": s, "code": code or "", "participants": n, "last": last.isoformat() if last else None}
        for s, code, n, last in rows
    ]


def participants(study):
    """The participant IDs with records in one study, sorted."""
    with connect() as con:
        rows = con.execute(
            "SELECT DISTINCT record->>'studentID' FROM log_record WHERE research_study = %s",
            (study,),
        ).fetchall()
    return sorted(r[0] for r in rows if r[0])


class Listener:
    """A connection listening for ATLAS's notifications; reconnects after a failure."""

    def __init__(self):
        self.con = None

    def _open(self):
        self.con = connect()
        self.con.execute(f"LISTEN {KEPT}")
        self.con.execute(f"LISTEN {FORGOTTEN}")

    def wait(self, timeout):
        """Wait up to `timeout` seconds; return the notifications that arrived as
        [(channel, payload dict)], at once when the first one comes."""
        try:
            if self.con is None or self.con.closed:
                self._open()
            got = list(self.con.notifies(timeout=max(0.01, timeout), stop_after=1))
            if got:
                got += list(self.con.notifies(timeout=0.01))
            return [(n.channel, json.loads(n.payload)) for n in got]
        except (psycopg.Error, ValueError) as e:
            log.warning("ZANY listener: %s; reconnecting", e)
            if self.con is not None:
                self.con.close()
            self.con = None
            time.sleep(min(timeout, 1.0))
            return []


class LoginFailed(Exception):
    """The research login was refused; its message says what to tell the person."""


def researcher_login(email, password):
    """Check a login against ATLAS: sign in with it, ask whether the account is a researcher, sign
    out. Stores nothing. Raises LoginFailed with a message for the person."""
    s = requests.Session()
    try:
        r = s.post(
            f"{config.ATLAS_URL}/api/method/login",
            data={"usr": email, "pwd": password},
            timeout=10,
        )
        if r.status_code != 200:
            raise LoginFailed("That email and password don't match a research login.")
        try:
            who = s.get(f"{config.ATLAS_URL}/api/method/atlas.research.researcher", timeout=10)
            researcher = who.status_code == 200 and who.json()["message"]["researcher"]
        finally:
            s.post(f"{config.ATLAS_URL}/api/method/logout", timeout=10)
    except requests.RequestException as e:
        log.warning("ATLAS login check failed: %s", e)
        raise LoginFailed("ATLAS didn't answer. Try again in a minute.") from e
    if not researcher:
        raise LoginFailed("That login isn't a researcher's.")
