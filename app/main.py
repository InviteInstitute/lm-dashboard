"""
The read API behind the cohort dashboard, built on FastAPI.

This side does no machine learning. It serves the state the daemon already
materialized (student_state, trigger_event) and handles the handful of small
writes the dashboard needs: the tracked roster, acks, notes, presence/picked
toggles, and the reset and polling control flags.

    uvicorn app.main:app --port 8000 --reload
"""
import asyncio
import json
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import config, db
from app.auth import BasicAuthMiddleware
from app.runs.ast_builder import extract_workspace_xml
from app.runs.humanize import humanize_text
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
# Compress JSON responses over ~1KB (the states payload with its run arrays
# shrinks ~5-10x) -- mostly felt over the remote tunnel. The SSE stream opts out
# via an explicit Content-Encoding so events are never buffered by gzip.
app.add_middleware(GZipMiddleware, minimum_size=1000)
# Outermost middleware (added last = runs first): gate the whole origin with HTTP
# Basic Auth when DASHBOARD_USER/PASSWORD are set for remote serving. No-op locally.
app.add_middleware(BasicAuthMiddleware)

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
    per-run edit distances and episode tracks but omits the bulky playground dump. Passing
    heavy=True adds `block`, the large playground_prompt tree, which only the
    detail modal renders, so it's fetched one student at a time on open instead
    of for the whole cohort on every poll."""
    out = {
        "studentID": s["studentID"],
        "display": s.get("display_id") or s["studentID"],   # most-recent casing for the UI
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
@app.get("/healthz")
def health():
    # Not at "/" so the static frontend mount can serve the dashboard there.
    return {"service": "luc-dashboard", "ok": True}


@app.get("/api/student_states/")
def student_states(students: str | None = None, classCode: str | None = None):
    """The dashboard's primary read: the materialized per-student state. Optional
    `students` (comma-separated) and `classCode` narrow the result. Rows sort by
    most recent activity; the dashboard derives a student's status from the
    triggers feed it already fetches."""
    # Presence heartbeat: this is the grid's per-tick poll, so a hit means a
    # dashboard is open and visible (the frontend stops polling when its tab is
    # hidden). The daemon reads this stamp to run its dead-man's switch -- it
    # pauses prod polling once no dashboard has polled for VIEWER_PRESENT_SECONDS.
    db.set_meta("viewer_last_seen", db.now().isoformat())
    ids = [x.strip() for x in students.split(",") if x.strip()] if students else None
    if ids and len(ids) > MAX_STUDENT_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"too many studentIDs (max {MAX_STUDENT_IDS})",
        )
    rows = [_shape_state(s) for s in db.list_student_states(ids, classCode)]
    rows.sort(key=lambda s: s["last_seen"] or "", reverse=True)
    return {"students": rows, "student_count": len(rows)}


# --------------------------------------------------------------------------
# live stream (Server-Sent Events)
# --------------------------------------------------------------------------
# One long-lived stream replaces the dashboard's four per-tick poll loops. The
# server watches a cheap change fingerprint once and pushes a `changed` event
# naming only the channels that actually moved, so the client refetches just
# those instead of blind-polling all four every POLL_MS. The open connection
# also is the viewer-presence signal: while a dashboard holds the stream we
# stamp viewer_last_seen, so the daemon's dead-man's switch keeps prod polling
# alive; when the tab closes, the stream ends and the switch pauses.
STREAM_TICK_SECONDS = 0.25     # how often to check for changes (data_version gate keeps this cheap)
STREAM_HEARTBEAT_TICKS = 40    # stamp presence + send a keepalive comment every N ticks (~10s)


def _changed_channels(prev, cur):
    """Channel names whose fingerprint changed between two snapshots. Pure and
    I/O-free so it can be unit-tested; `prev is None` (the first tick) is never a
    change."""
    if prev is None:
        return []
    return [name for name in cur if cur.get(name) != prev.get(name)]


@app.get("/api/stream/")
async def stream(request: Request, once: bool = False):
    """Server-Sent Events feed. Emits `hello` immediately (the client does one
    full fetch on connect), then `changed` events carrying the list of channels
    that moved. `once=true` returns just the hello and closes -- used by tests so
    they never block on the live loop."""
    async def gen():
        yield "event: hello\ndata: {}\n\n"
        if once:
            return
        prev = await run_in_threadpool(db.data_fingerprint)
        await run_in_threadpool(db.set_meta, "viewer_last_seen", db.now().isoformat())
        # O(1) change gate: PRAGMA data_version on a dedicated read-only
        # connection bumps when ANY other connection commits, so quiet ticks
        # cost one pragma read instead of the four fingerprint queries. This is
        # what makes the 0.25s tick free.
        probe = await run_in_threadpool(db.data_version_probe)
        dv = await run_in_threadpool(db.data_version, probe)
        ticks = 0
        try:
            while not await request.is_disconnected():
                await asyncio.sleep(STREAM_TICK_SECONDS)
                dv_now = await run_in_threadpool(db.data_version, probe)
                if dv_now != dv:
                    dv = dv_now
                    cur = await run_in_threadpool(db.data_fingerprint)
                    changed = _changed_channels(prev, cur)
                    if changed:
                        prev = cur
                        yield f"event: changed\ndata: {json.dumps({'channels': changed})}\n\n"
                ticks += 1
                if ticks % STREAM_HEARTBEAT_TICKS == 0:
                    await run_in_threadpool(db.set_meta, "viewer_last_seen", db.now().isoformat())
                    yield ": keepalive\n\n"
        finally:
            probe.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no",
                 # Pre-set encoding: GZipMiddleware skips responses that already
                 # carry one, so events are never buffered inside a gzip window.
                 "Content-Encoding": "identity"},
    )


@app.get("/api/student_states/{student_id}/")
def student_state_detail(student_id: str):
    """The heavy payload for a single student, the cohort fields plus the
    playground prompt the grid leaves out. The detail modal calls this on open.
    Returns 404 when the student is tracked but has no materialized state yet."""
    rows = db.list_student_states([student_id])
    if not rows:
        raise HTTPException(status_code=404, detail="no state for that student")
    payload = _shape_state(rows[0], heavy=True)
    # Readable program listing (feature #12): the student's latest blocks with
    # their parameters spelled out, incl. the numbers the edit-distance AST drops.
    # Best-effort and isolated -- a parse miss just yields "".
    proj = db.latest_project(student_id)
    payload["block"]["readable"] = (
        humanize_text(extract_workspace_xml({"project": proj})) if proj else "")
    return payload


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


@app.get("/api/switches/")
def switches():
    """Identity switches (a handle's casing flipped, or it showed up in a new
    class) detected for tracked students, newest first. The dashboard polls this
    for the live toast and the reviewable Switches feed."""
    items = [{
        "id": r["id"], "studentID": r["studentID"], "kind": r["kind"],
        "from": r["from_value"], "to": r["to_value"],
        "ts": _iso(db.db_to_dt(r["ts"])),
        "acknowledged": bool(r["acknowledged"]),
    } for r in db.list_switches(limit=100)]
    return {"switches": items, "unacked": sum(1 for i in items if not i["acknowledged"])}


class SwitchAckBody(BaseModel):
    id: int


@app.post("/api/switches/ack/")
def ack_switch(body: SwitchAckBody):
    """Dismiss one switch so it stops showing as new in the feed."""
    return {"acknowledged": db.ack_switch(body.id)}


class OutboxBody(BaseModel):
    op: str
    payload: dict | None = None
    error: str | None = None


@app.post("/api/outbox/")
def outbox_store(body: OutboxBody):
    """Park a researcher input whose primary write failed its retries. The
    dashboard sends the original request body verbatim so nothing typed or
    clicked is ever lost -- the row can be replayed by hand later."""
    db.record_outbox(body.op,
                     json.dumps(body.payload) if body.payload is not None else None,
                     body.error)
    return {"stored": True}


@app.get("/api/outbox/")
def outbox_list():
    """The parked failed inputs, newest first (inspection/replay)."""
    rows = db.list_outbox()
    return {"outbox": rows, "count": len(rows)}


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
    """Stream a CSV snapshot of all current data as a zip the browser downloads.
    A pure read built entirely in memory, the database and filesystem are never
    touched."""
    stamp = db.now()
    name = f"lm-dashboard_export_{stamp.strftime('%Y-%m-%d_%H%M%S')}.zip"
    return Response(
        content=db.export_zip_bytes(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/reset/")
def reset():
    """Clear all local student data (logs, episodes, run/trigger state, flags), the
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
    source: str = "roster"            # 'roster' | 'intervention'
    trigger_id: int | None = None     # set only for intervention picks
    trigger_type: str | None = None


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
    db.set_picked(sid, body.picked, source=body.source,
                  trigger_id=body.trigger_id, trigger_type=body.trigger_type)
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


# --------------------------------------------------------------------------
# static frontend (single-origin remote serving)
# --------------------------------------------------------------------------
# Serve the built React app (frontend/dist) at the root so ONE Cloudflare tunnel
# exposes a single origin for both the UI and /api -- no second service, no CORS.
# Mounted last (after every /api route, so it never shadows them) and only when a
# build exists, so the API-only local-dev flow (Vite on :3000) is unaffected.
import os
from fastapi.staticfiles import StaticFiles

_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="spa")
