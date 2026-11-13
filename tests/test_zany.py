"""ZANY's study logs as a source (app/zany.py, app/pipeline/zany_source.py), against a stand-in for
ATLAS-invite's log store: a schema in the test database with ATLAS's log_record table."""

import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app import config, db, zany
from app.main import UNLOCK_COOKIE, _unlock_failures, _unlock_signer
from app.pipeline import workers, zany_source

STUDY = "STUDY-0001"

# ATLAS-invite's log_record (atlas/zany_logs.py SCHEMA), the one table lmdash_reader may read.
LOG_RECORD = """
CREATE TABLE log_record (
    research_participant text NOT NULL,
    page_session text NOT NULL,
    id bigint NOT NULL,
    study_session text NOT NULL,
    research_study text NOT NULL,
    event_type text NOT NULL,
    record jsonb NOT NULL,
    stored_at timestamptz NOT NULL,
    seq bigint GENERATED ALWAYS AS IDENTITY,
    PRIMARY KEY (research_participant, page_session, id)
)"""


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """A fresh stand-in store for each test, and the app pointed at it."""
    url = config.DATABASE_URL
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("DROP SCHEMA IF EXISTS zany_store CASCADE")
        con.execute("CREATE SCHEMA zany_store")
        con.execute("SET search_path TO zany_store")
        con.execute(LOG_RECORD)
    sep = "&" if "?" in url else "?"
    monkeypatch.setattr(config, "ZANY_LOG_DSN", f"{url}{sep}options=-csearch_path%3Dzany_store")
    _unlock_failures.clear()
    yield
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("DROP SCHEMA zany_store CASCADE")


def keep(pid, i, event="blockCreated", study=STUDY, code="DEMO", at=None):
    """Store one record as ATLAS's zany_logs.add does; returns its seq."""
    record = {
        "id": 1793216880123000 + i,
        "eventType": event,
        "classCode": code,
        "studentID": pid,
        "project": "{}",
        "raw_message": json.dumps({"eventType": event, "sessionID": "page"}),
        "received_at": "2026-11-13T10:00:00+00:00",
    }
    with zany.connect() as con:
        return con.execute(
            "INSERT INTO log_record (research_participant, page_session, id, study_session,"
            " research_study, event_type, record, stored_at) VALUES (%s, 'page', %s, 'SESS', %s, %s, %s, %s)"
            " RETURNING seq",
            (f"RP-{pid}", record["id"], study, event, json.dumps(record), at or datetime.now(UTC)),
        ).fetchone()[0]


def test_a_zany_student_has_an_id_no_reflecks_student_can_have():
    sid = zany.key(STUDY, "R01")
    assert zany.is_zany(sid) and not zany.is_zany("R01")
    assert zany.split(sid) == (STUDY, "R01")


def test_drain_stores_and_routes_only_tracked_students_and_passes_every_row():
    r01, r02 = db.canon_id(zany.key(STUDY, "R01")), db.canon_id(zany.key(STUDY, "R02"))
    keep("R01", 0)
    keep("R02", 1)
    last = keep("R01", 2, "runProject")
    cursor = zany_source.get_cursor()
    assert zany_source.drain(cursor, {r01}) == 2
    assert cursor.last_source_id == last  # past R02's row too
    assert zany_source.drain(zany_source.get_cursor(), {r01}) == 0  # resumes after the last row
    rows = db._query("SELECT studentID, eventType, zany_seq FROM vex_log ORDER BY zany_seq")
    assert [(r["eventType"], db.canon_id(r["studentID"])) for r in rows] == [
        ("blockCreated", r01),
        ("runProject", r01),
    ]
    assert r02 not in {db.canon_id(r["studentID"]) for r in rows}
    assert workers.has_worker(r01)


def test_drain_skips_rows_from_before_the_session():
    sid = db.canon_id(zany.key(STUDY, "R01"))
    keep("R01", 0, at=datetime.now(UTC) - timedelta(hours=3))
    keep("R01", 1)
    assert (
        zany_source.drain(
            zany_source.get_cursor(), {sid}, since=datetime.now(UTC) - timedelta(hours=1)
        )
        == 1
    )


def test_backfill_brings_in_a_students_history_once():
    keep("R01", 0)
    keep("R01", 1)
    keep("R02", 2)
    sid = zany.key(STUDY, "r01")  # typed in another case
    assert zany_source.backfill_student(sid) == 2
    assert zany_source.backfill_student(sid) == 0


def test_the_listener_hears_atlas_and_forgetting_drops_the_mirror():
    listener = zany.Listener()
    assert listener.wait(0.05) == []  # opens and listens
    with zany.connect() as con:
        con.execute(
            "SELECT pg_notify(%s, %s)",
            (zany.FORGOTTEN, json.dumps({"study": STUDY, "participant": "R01"})),
        )
    heard = listener.wait(2)
    assert heard == [(zany.FORGOTTEN, {"study": STUDY, "participant": "R01"})]
    sid = zany.key(STUDY, "R01")
    keep("R01", 0)
    db.tracked_add(sid)
    zany_source.backfill_student(sid)
    db.mark_backfilled(sid)
    db.forget_student(sid)
    assert db._query("SELECT count(*) AS n FROM vex_log")[0]["n"] == 0
    assert db.tracked_list()[0]["backfilled"] is False  # backfilled again from what is left


def test_restarting_drops_every_zany_mirror_but_not_reflecks():
    db.insert_message_and_log(
        {
            "studentID": "cobra3",
            "classCode": "C1",
            "eventType": "runProject",
            "project": "",
            "raw_message": "{}",
            "source_event_id": 1,
            "event_time": db.now(),
        }
    )
    keep("R01", 0)
    zany_source.backfill_student(zany.key(STUDY, "R01"))
    db.forget_all_zany()
    left = [r["studentID"] for r in db._query("SELECT studentID FROM vex_log")]
    assert left == ["cobra3"]


def test_studies_and_participants_list_what_the_store_has():
    keep("R02", 0)
    keep("R01", 1)
    keep("X1", 2, study="STUDY-0002", code="OTHER")
    studies = {s["study"]: s for s in zany.studies()}
    assert studies[STUDY]["code"] == "DEMO" and studies[STUDY]["participants"] == 2
    assert zany.participants(STUDY) == ["R01", "R02"]


# ---- the API ----


def unlock(client):
    client.cookies.set(UNLOCK_COOKIE, _unlock_signer.sign(b"ok").decode())


def test_unlocking_checks_the_research_login_with_atlas_and_limits_tries(client, monkeypatch):
    calls = []

    def login(email, password):
        calls.append(email)
        if password != "right":
            raise zany.LoginFailed("That email and password don't match a research login.")

    monkeypatch.setattr(zany, "researcher_login", login)
    keep("R01", 0)
    assert client.get("/api/zany/").json() == {"enabled": True, "unlocked": False, "studies": []}
    r = client.post(
        "/api/zany/unlock/", json={"email": "research@example.org", "password": "wrong"}
    )
    assert r.status_code == 401
    r = client.post(
        "/api/zany/unlock/", json={"email": " research@example.org ", "password": "right"}
    )
    assert r.status_code == 200 and r.json()["studies"][0]["study"] == STUDY
    assert calls[-1] == "research@example.org"
    assert client.get("/api/zany/").json()["unlocked"] is True
    for _ in range(5):
        client.post("/api/zany/unlock/", json={"email": "x", "password": "wrong"})
    r = client.post("/api/zany/unlock/", json={"email": "x", "password": "right"})
    assert r.status_code == 429


def test_a_zany_board_needs_an_unlocked_browser(client):
    keep("R01", 0)
    assert client.post("/api/source/", json={"source": f"zany:{STUDY}"}).status_code == 403
    unlock(client)
    assert client.post("/api/source/", json={"source": "zany:STUDY-9999"}).status_code == 400
    assert client.post("/api/source/", json={"source": f"zany:{STUDY}"}).json() == {
        "source": f"zany:{STUDY}"
    }
    assert client.get("/api/tracked/").status_code == 200
    client.cookies.delete(UNLOCK_COOKIE)
    r = client.get("/api/tracked/")
    assert r.status_code == 403 and r.json()["detail"] == "zany_locked"
    # It can always go back to Reflecks.
    assert client.post("/api/source/", json={"source": "reflecks"}).status_code == 200
    assert client.get("/api/tracked/").status_code == 200


def test_a_zany_board_tracks_participant_ids_in_its_study_and_shows_them_plain(client):
    keep("R01", 0)
    db.tracked_add("cobra3")  # a Reflecks student on the same board
    unlock(client)
    client.post("/api/source/", json={"source": f"zany:{STUDY}"})
    client.post("/api/tracked/", json={"studentID": "R01"})
    tracked = client.get("/api/tracked/").json()
    assert [(t["studentID"], t["display"]) for t in tracked["tracked"]] == [
        (db.canon_id(zany.key(STUDY, "R01")), "r01")
    ]
    client.post("/api/source/", json={"source": "reflecks"})
    assert [t["studentID"] for t in client.get("/api/tracked/").json()["tracked"]] == ["cobra3"]


def test_unlock_needs_the_store_connected(client, monkeypatch):
    monkeypatch.setattr(config, "ZANY_LOG_DSN", None)
    assert client.get("/api/zany/").json()["enabled"] is False
    assert client.post("/api/zany/unlock/", json={"email": "a", "password": "b"}).status_code == 404
