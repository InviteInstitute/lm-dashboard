"""
The read API behind the cohort dashboard, built on FastAPI.

This side does no machine learning. It serves the state the daemon already
materialized (student_state, trigger_event) and handles the handful of small
writes the dashboard needs: the tracked roster, acks, notes, presence/picked
toggles, and the reset and polling control flags.

    uvicorn app.main:app --port 8000 --reload
"""
from datetime import timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config, db
from app.constants import (
    TRIGGER_RECENT_SECONDS, MAX_STUDENT_IDS, TRIGGER_LABELS,
)

app = FastAPI(title="LM Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create the schema if it isn't there yet (a no-op otherwise), so a fresh clone
# works no matter whether the API or the daemon happens to start first.
db.init_db()


# --------------------------------------------------------------------------
# shaping
# --------------------------------------------------------------------------
def _iso(dt):
    return dt.isoformat() if dt else None


def _shape_state(s, heavy=False):
    """Turn a materialized student_state row into the dashboard's JSON payload.

    By default this is the light shape the cohort grid uses: it carries the
    strategy and episode tracks but omits the bulky playground dump. Passing
    heavy=True adds `block`, the large playground_prompt tree, which only the
    detail modal renders, so it's fetched one student at a time on open instead
    of for the whole cohort on every poll."""
    out = {
        "studentID": s["studentID"],
        "classCode": s["classCode"],
        "run_count": s["run_count"],
        "event_count": s["event_count"],
        "last_seen": _iso(s["last_event_time"]),
        "runs": s["runs"] or {},                            # {runs:[{index,edit_distance,ts}], run_count}
        "episodes": s["episodes"],                          # {events, episodes, pauses,...}
        "updated_at": _iso(s["updated_at"]),
    }
    if heavy:
        out["block"] = {"llm_prompt": s["playground_prompt"],
                        "timestamp": _iso(s["playground_time"])}
    return out


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@app.get("/")
def health():
    return {"service": "luc-dashboard", "ok": True}


@app.get("/api/student_states/")
def student_states(students: str | None = None, classCode: str | None = None):
    """The dashboard's primary read: the materialized per-student state. Optional
    `students` (comma-separated) and `classCode` narrow the result. Rows sort by
    most recent activity; the dashboard derives a student's status from the
    triggers feed it already fetches."""
    ids = [x.strip() for x in students.split(",") if x.strip()] if students else None
    if ids and len(ids) > MAX_STUDENT_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"too many studentIDs (max {MAX_STUDENT_IDS})",
        )
    rows = [_shape_state(s) for s in db.list_student_states(ids, classCode)]
    rows.sort(key=lambda s: s["last_seen"] or "", reverse=True)
    return {"students": rows, "student_count": len(rows)}


@app.get("/api/student_states/{student_id}/")
def student_state_detail(student_id: str):
    """The heavy payload for a single student, the cohort fields plus the
    playground prompt the grid leaves out. The detail modal calls this on open.
    Returns 404 when the student is tracked but has no materialized state yet."""
    rows = db.list_student_states([student_id])
    if not rows:
        raise HTTPException(status_code=404, detail="no state for that student")
    return _shape_state(rows[0], heavy=True)


@app.get("/api/triggers/")
def triggers():
    """The intervention feed: still-open triggers plus any resolved within the
    last TRIGGER_RECENT_SECONDS, newest first, unacknowledged only."""
    now = db.now()
    cutoff = now - timedelta(seconds=TRIGGER_RECENT_SECONDS)
    items, counts = [], {}
    for t in db.triggers_feed(cutoff):
        active = t["resolved_at"] is None
        d = t["detail"] or {}
        started = t["started_at"]
        items.append({
            "id": t["id"], "studentID": t["studentID"], "trigger_type": t["trigger_type"],
            "label": d.get("label", t["trigger_type"]), "value": d.get("value"),
            "started_at": _iso(started),
            "resolved_at": _iso(t["resolved_at"]),
            "active": active,
            "age_seconds": (now - started).total_seconds() if started else None,
        })
        if active:
            counts[t["trigger_type"]] = counts.get(t["trigger_type"], 0) + 1
    return {"triggers": items,
            "active_count": sum(1 for i in items if i["active"]),
            "counts": counts}


class AckBody(BaseModel):
    id: int | None = None
    studentID: str | None = None


@app.post("/api/triggers/ack/")
def ack_trigger(body: AckBody):
    """Dismiss a single trigger by id, or every open trigger for a student."""
    if body.id is not None:
        n = db.ack_by_id(body.id)
    elif body.studentID:
        n = db.ack_by_student(body.studentID)
    else:
        raise HTTPException(status_code=400, detail="provide id or studentID")
    return {"acknowledged": n}


class TrackBody(BaseModel):
    studentID: str | None = None
    remove: bool = False


@app.get("/api/tracked/")
def tracked_list():
    rows = db.tracked_list()
    return {"tracked": rows, "count": len(rows)}


@app.post("/api/tracked/")
def tracked_mutate(body: TrackBody):
    """Start or stop tracking a student. {studentID} adds them (the daemon then
    backfills); {studentID, remove: true} stops tracking and deletes their data."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    if body.remove:
        db.tracked_remove(sid)
        return {"removed": sid}
    db.tracked_add(sid)
    return {"added": sid}


@app.post("/api/export/")
def export():
    """Write a CSV snapshot of all current data to exports/<timestamp>/. A pure
    read, the database is never touched."""
    stamp = db.now()
    out_dir, rows = db.export_csv(
        str(config.BASE_DIR / "exports" / f"export_{stamp.strftime('%Y-%m-%d_%H%M%S')}")
    )
    return {"exported": True, "at": stamp.isoformat(), "dir": out_dir, "rows": rows}


@app.post("/api/reset/")
def reset():
    """Clear all local student data (logs, episodes, HMM state, flags), the
    researcher notes, and the interview-pick state (picked toggles + pick
    history), and signal the daemon to drop its in-memory workers. Tracked
    students stay tracked, presence is kept, and the board rebuilds from new
    activity. A CSV snapshot, notes and picks included, is written to
    exports/reset_<timestamp>/ first, so nothing is actually lost. Local only;
    production is never touched.

    The order matters: we stamp meta['reset_requested_at'] (which the daemon
    watches, so it drops its workers and re-wipes any row a race leaves behind)
    and also wipe right away here, so the dashboard clears immediately."""
    stamp = db.now()
    backup_dir, _ = db.export_csv(
        str(config.BASE_DIR / "exports" / f"reset_{stamp.strftime('%Y-%m-%d_%H%M%S')}")
    )
    db.set_meta("reset_requested_at", stamp.isoformat())
    db.reset_all()
    return {"reset": True, "at": stamp.isoformat(), "backup": backup_dir}


def _polling_enabled() -> bool:
    """Polling is on unless the flag is explicitly "0"; anything else (including
    a missing flag) counts as enabled."""
    return db.get_meta("polling_enabled") != "0"


class PollingBody(BaseModel):
    enabled: bool


@app.get("/api/polling/")
def polling_status():
    """Report whether the daemon is currently polling production. The dashboard's
    pause toggle reads this to stay in sync across open tabs."""
    return {"enabled": _polling_enabled()}


class PresenceBody(BaseModel):
    studentID: str
    present: bool


class PickedBody(BaseModel):
    studentID: str
    picked: bool


@app.post("/api/presence/")
def set_presence(body: PresenceBody):
    """Set whether a tracked student is present in the room. Persisted on
    tracked_student, so it's included in the CSV export."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    db.set_presence(sid, body.present)
    return {"studentID": sid, "present": body.present}


@app.post("/api/picked/")
def set_picked(body: PickedBody):
    """Set whether a tracked student has been picked/interviewed this session.
    Persisted on tracked_student (with picked_at), so it's in the CSV export."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    db.set_picked(sid, body.picked)
    return {"studentID": sid, "picked": body.picked}


TRIGGER_TYPES = tuple(TRIGGER_LABELS)


def _disabled_triggers() -> set[str]:
    raw = db.get_meta("disabled_triggers") or ""
    return {t for t in raw.split(",") if t}


class TriggerConfigBody(BaseModel):
    trigger_type: str
    enabled: bool


@app.get("/api/triggers/config/")
def triggers_config():
    """Report which trigger types are enabled (all on by default) along with
    their display labels."""
    disabled = _disabled_triggers()
    return {
        "enabled": {t: (t not in disabled) for t in TRIGGER_TYPES},
        "labels": TRIGGER_LABELS,
    }


@app.post("/api/triggers/config/")
def set_triggers_config(body: TriggerConfigBody):
    """Turn a trigger type on or off. Disabling it makes the daemon stop firing
    that type and resolve its open alerts on the next tick. The setting lives in
    meta and the raw event log is left alone, so re-enabling takes effect at once."""
    if body.trigger_type not in TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail="unknown trigger_type")
    disabled = _disabled_triggers()
    if body.enabled:
        disabled.discard(body.trigger_type)
    else:
        disabled.add(body.trigger_type)
    db.set_meta("disabled_triggers", ",".join(sorted(disabled)))
    return {"enabled": {t: (t not in disabled) for t in TRIGGER_TYPES}}


class NoteBody(BaseModel):
    studentID: str
    text: str
    trigger_id: int | None = None
    trigger_type: str | None = None


@app.post("/api/notes/")
def add_note(body: NoteBody):
    """Record an observation for a learner. trigger_id/trigger_type tie it to the
    alert it was written from; omit both for a free-standing note. Persisted on
    the note table, so it's included in the CSV export."""
    sid = (body.studentID or "").strip()
    text = (body.text or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    return db.add_note(sid, text, body.trigger_id, body.trigger_type)


@app.get("/api/notes/")
def list_notes(studentID: str | None = None):
    """Every note for a learner, in chronological order."""
    sid = (studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    notes = db.list_notes(sid)
    return {"notes": notes, "count": len(notes)}


@app.post("/api/polling/")
def set_polling(body: PollingBody):
    """Pause or resume the daemon's production polling. While paused the daemon
    makes no requests to prod at all; it keeps running locally and picks back up
    within about a second of being re-enabled. This is how you stop loading prod
    between sessions without killing the process. Purely a local control flag,
    prod is untouched either way."""
    db.set_meta("polling_enabled", "1" if body.enabled else "0")
    return {"enabled": body.enabled}
