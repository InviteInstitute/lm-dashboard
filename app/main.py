"""
FastAPI read API for the cohort dashboard.

Reads the materialized state the daemon writes (student_state, trigger_event)
and owns the tracked allowlist + acks. No ML here -- that's the daemon's job.

    uvicorn app.main:app --port 8000 --reload
"""
from datetime import timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config, db

STUCK_STATE = 2
STATE_LABELS = {0: "iterator", 1: "explorer", 2: "stuck"}
# Resolved triggers linger this long in the feed before dropping off.
TRIGGER_RECENT_SECONDS = 120
# Cap how many ids /api/student_states/?students= can request -- well under
# SQLite's SQLITE_MAX_VARIABLE_NUMBER and large enough to cover any real cohort.
MAX_STUDENT_IDS = 500

app = FastAPI(title="LUC Cohort Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure the schema exists (no-op on an existing DB) so a fresh clone works
# whether the API or the daemon starts first.
db.init_db()


# --------------------------------------------------------------------------
# shaping
# --------------------------------------------------------------------------
def _iso(dt):
    return dt.isoformat() if dt else None


def _shape_state(s):
    """Materialized student_state row -> the viewer's payload."""
    runs_blob = s["runs"] or {}
    run_list = runs_blob.get("runs", [])
    state_sequence = [r["hmm_state"] for r in run_list if r.get("hmm_state") is not None]
    return {
        "studentID": s["studentID"],
        "classCode": s["classCode"],
        "current_state": s["current_state"],
        "current_label": s["state_label"],
        "stuck": s["stuck"],
        "consecutive_stuck": s["consecutive_stuck"],
        "run_count": s["run_count"],
        "event_count": s["event_count"],
        "last_seen": _iso(s["last_event_time"]),
        "state_sequence": state_sequence,
        "hmm": runs_blob,                                   # {runs, obs_labels, run_count}
        "episodes": s["episodes"],                          # {events, episodes, pauses,...}
        "block": {"llm_prompt": s["playground_prompt"],
                  "timestamp": _iso(s["playground_time"])},
        "updated_at": _iso(s["updated_at"]),
    }


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@app.get("/")
def health():
    return {"service": "luc-dashboard", "ok": True}


@app.get("/api/student_states/")
def student_states(students: str | None = None, classCode: str | None = None):
    """Read the materialized student_state table (written by the daemon)."""
    ids = [x.strip() for x in students.split(",") if x.strip()] if students else None
    if ids and len(ids) > MAX_STUDENT_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"too many studentIDs (max {MAX_STUDENT_IDS})",
        )
    rows = [_shape_state(s) for s in db.list_student_states(ids, classCode)]
    rows.sort(key=lambda s: s["last_seen"] or "", reverse=True)
    rows.sort(key=lambda s: s["stuck"], reverse=True)
    return {
        "students": rows,
        "student_count": len(rows),
        "stuck_count": sum(1 for s in rows if s["stuck"]),
        "stuck_state": STUCK_STATE,
        "state_labels": STATE_LABELS,
    }


@app.get("/api/triggers/")
def triggers():
    """Active triggers + ones resolved in the last TRIGGER_RECENT_SECONDS,
    newest first, unacknowledged only."""
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
    """Acknowledge (dismiss) a trigger by id, or all open ones for a student."""
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
    """POST {studentID} -> track (daemon backfills); {studentID, remove:true} -> stop + delete."""
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
    """Save a CSV snapshot of all current data to exports/<timestamp>/. Read-only;
    never modifies the database."""
    stamp = db.now()
    out_dir, rows = db.export_csv(
        str(config.BASE_DIR / "exports" / f"export_{stamp.strftime('%Y-%m-%d_%H%M%S')}")
    )
    return {"exported": True, "at": stamp.isoformat(), "dir": out_dir, "rows": rows}


@app.post("/api/reset/")
def reset():
    """Wipe all local student data (logs, episodes, HMM state, flags) and tell the
    daemon to drop its in-memory workers. Students stay tracked; the board rebuilds
    from new activity. NO backup -- call POST /api/export/ first for a CSV copy.
    Local only; production is untouched.

    Sets the meta flag (so the daemon drops its workers and re-wipes any row a race
    leaves behind) and wipes now so the UI clears immediately."""
    stamp = db.now().isoformat()
    db.set_meta("reset_requested_at", stamp)
    db.reset_all()
    return {"reset": True, "at": stamp}


def _polling_enabled() -> bool:
    """Default ON: only an explicit "0" pauses polling."""
    return db.get_meta("polling_enabled") != "0"


class PollingBody(BaseModel):
    enabled: bool


@app.get("/api/polling/")
def polling_status():
    """Whether the daemon is currently polling production (the dashboard's pause
    toggle reads this)."""
    return {"enabled": _polling_enabled()}


class PresenceBody(BaseModel):
    studentID: str
    present: bool


class PickedBody(BaseModel):
    studentID: str
    picked: bool


@app.post("/api/presence/")
def set_presence(body: PresenceBody):
    """Toggle whether a tracked student is present in the room. Stored on
    tracked_student, so it exports with the CSV snapshot."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    db.set_presence(sid, body.present)
    return {"studentID": sid, "present": body.present}


@app.post("/api/picked/")
def set_picked(body: PickedBody):
    """Toggle whether a tracked student has been picked/interviewed this session.
    Stored on tracked_student (with picked_at), so it exports with the CSV."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    db.set_picked(sid, body.picked)
    return {"studentID": sid, "picked": body.picked}


@app.post("/api/polling/")
def set_polling(body: PollingBody):
    """Pause or resume the daemon's production polling. When paused the daemon
    makes ZERO requests to prod -- it keeps running locally and resumes within a
    second of being re-enabled. Lets you stop loading prod between sessions
    without killing the process. Local control flag only; prod is untouched."""
    db.set_meta("polling_enabled", "1" if body.enabled else "0")
    return {"enabled": body.enabled}
