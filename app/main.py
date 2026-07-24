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

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from app import config, db
from app.auth import SessionAuthMiddleware, authenticate, ensure_bootstrap_researcher
from app.runs.ast_builder import extract_workspace_xml
from app.runs.humanize import humanize_text
from app.constants import (
    TRIGGER_RECENT_SECONDS, MAX_STUDENT_IDS, TRIGGER_LABELS,
)

app = FastAPI(title="LM Dashboard")
# Middleware runs outermost-first in reverse add order, so these are added
# inner -> outer: GZip (compresses route responses) inside SessionAuthMiddleware
# (the /api gate) inside SessionMiddleware (parses the signed session cookie)
# inside CORS (handles preflight + credentialed cross-origin in dev). The result
# order is CORS -> Session -> SessionAuth -> GZip -> routes.
#
# The SSE stream opts out of gzip via an explicit Content-Encoding so events are
# never buffered by a gzip window.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SessionAuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET,
                   same_site="lax", https_only=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,          # session cookie rides cross-origin in dev
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create the schema if it isn't there yet (a no-op otherwise), so a fresh clone
# works no matter whether the API or the daemon happens to start first.
db.init_db()
# Interim: seed the shared researcher login from the env-file prod creds until
# per-researcher accounts + the login UI land (see app/auth.py).
ensure_bootstrap_researcher()


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


# --------------------------------------------------------------------------
# auth: researcher login/logout + the current-session probe the SPA calls on
# load. Everything else under /api requires the session these establish (see
# app/auth.SessionAuthMiddleware).
# --------------------------------------------------------------------------
class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/login/")
async def login(body: LoginBody, request: Request):
    researcher = await run_in_threadpool(authenticate, body.username, body.password)
    if not researcher:
        raise HTTPException(status_code=401, detail="invalid username or password")
    request.session["researcher_id"] = researcher["id"]
    request.session["username"] = researcher["username"]
    return {"id": researcher["id"], "username": researcher["username"]}


@app.post("/api/logout/")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me/")
async def me(request: Request):
    # Reachable only past the auth gate, so a session always exists here; the SPA
    # reads a 401 from this route (via the gate) as "show the login screen".
    return {"id": request.session.get("researcher_id"),
            "username": request.session.get("username")}


async def current_workspace_id(request: Request) -> int:
    """The workspace the logged-in researcher is acting in. Resolved once from the
    session (guaranteed present past the auth gate) and cached on request.state,
    so every data route scopes to the caller's own board."""
    cached = getattr(request.state, "workspace_id", None)
    if cached is not None:
        return cached
    rid = request.session.get("researcher_id")
    ids = await run_in_threadpool(db.workspace_ids_for_researcher, rid)
    wsid = ids[0] if ids else await run_in_threadpool(
        db.ensure_workspace_for_researcher, rid, str(rid))
    request.state.workspace_id = wsid
    return wsid


@app.get("/api/student_states/")
def student_states(classCode: str | None = None,
                   wsid: int = Depends(current_workspace_id)):
    """The dashboard's primary read: the materialized state for the students on
    this workspace's roster. Optional `classCode` narrows the result. Rows sort by
    most recent activity; the dashboard derives a student's status from the
    triggers feed it already fetches."""
    # Presence heartbeat: this is the grid's per-tick poll, so a hit means this
    # workspace's dashboard is open and visible (the frontend stops polling when
    # its tab is hidden). The daemon reads this per-workspace stamp for its
    # dead-man's switch -- it stops polling a board's students once no dashboard
    # has polled for VIEWER_PRESENT_SECONDS.
    db.set_workspace_setting(wsid, "viewer_last_seen", db.now().isoformat())
    rows = [_shape_state(s) for s in db.list_student_states(class_code=classCode, workspace_id=wsid)]
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
async def stream(request: Request, once: bool = False,
                 wsid: int = Depends(current_workspace_id)):
    """Server-Sent Events feed. Emits `hello` immediately (the client does one
    full fetch on connect), then `changed` events carrying the list of channels
    that moved. `once=true` returns just the hello and closes -- used by tests so
    they never block on the live loop.

    The change signal is still global (any student's change wakes every open
    board, which then refetches its own roster-scoped data); holding the stream is
    this workspace's viewer-presence heartbeat for the daemon's dead-man switch."""
    async def gen():
        yield "event: hello\ndata: {}\n\n"
        if once:
            return
        prev = await run_in_threadpool(db.data_fingerprint)
        await run_in_threadpool(db.set_workspace_setting, wsid, "viewer_last_seen",
                                db.now().isoformat())
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
                    await run_in_threadpool(db.set_workspace_setting, wsid,
                                            "viewer_last_seen", db.now().isoformat())
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
def student_state_detail(student_id: str, wsid: int = Depends(current_workspace_id)):
    """The heavy payload for a single student, the cohort fields plus the
    playground prompt the grid leaves out. The detail modal calls this on open.
    Returns 404 when the student isn't on this workspace's roster or has no
    materialized state yet."""
    rows = db.list_student_states([student_id], workspace_id=wsid)
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
def triggers(wsid: int = Depends(current_workspace_id)):
    """The intervention feed for this workspace: still-open triggers on its roster
    plus any resolved within the last TRIGGER_RECENT_SECONDS, newest first, that
    this workspace hasn't dismissed."""
    now = db.now()
    cutoff = now - timedelta(seconds=TRIGGER_RECENT_SECONDS)
    feed = db.triggers_feed(cutoff, workspace_id=wsid)
    # Each alert also carries the student's PREVIOUS trigger (what and when), so
    # the card can say "last: Wheel-spinning · 10:24". One history fetch per
    # distinct student in the feed; the feed is small, so this stays cheap.
    history = {sid: db.trigger_history(sid, workspace_id=wsid)
               for sid in {t["studentID"] for t in feed}}
    items, counts = [], {}
    for t in feed:
        active = t["resolved_at"] is None
        d = t["detail"] or {}
        started = t["started_at"]
        prev = next((h for h in history[t["studentID"]]
                     if h["id"] != t["id"] and h["started_at"] and started
                     and h["started_at"] <= started), None)
        pd = (prev or {}).get("detail") or {}
        items.append({
            "id": t["id"], "studentID": t["studentID"], "trigger_type": t["trigger_type"],
            "label": d.get("label", t["trigger_type"]), "value": d.get("value"),
            "started_at": _iso(started),
            "resolved_at": _iso(t["resolved_at"]),
            "active": active,
            "age_seconds": (now - started).total_seconds() if started else None,
            "prev": {
                "trigger_type": prev["trigger_type"],
                "label": pd.get("label", prev["trigger_type"]),
                "at": _iso(prev["started_at"]),
            } if prev else None,
        })
        if active:
            counts[t["trigger_type"]] = counts.get(t["trigger_type"], 0) + 1
    return {"triggers": items,
            "active_count": sum(1 for i in items if i["active"]),
            "counts": counts}


@app.get("/api/triggers/history/")
def trigger_history(studentID: str, wsid: int = Depends(current_workspace_id)):
    """One student's full trigger history, newest first -- open, resolved, and
    dismissed alike -- with this workspace's dismiss state. The detail modal
    renders this as the trigger-history grid."""
    if not studentID:
        raise HTTPException(status_code=400, detail="provide studentID")
    rows = []
    for t in db.trigger_history(studentID, workspace_id=wsid):
        d = t["detail"] or {}
        rows.append({
            "id": t["id"], "trigger_type": t["trigger_type"],
            "label": d.get("label", t["trigger_type"]), "value": d.get("value"),
            "started_at": _iso(t["started_at"]),
            "resolved_at": _iso(t["resolved_at"]),
            "status": ("dismissed" if t["acknowledged"]
                       else "active" if t["resolved_at"] is None else "resolved"),
        })
    return {"history": rows, "count": len(rows)}


class AckBody(BaseModel):
    id: int | None = None
    studentID: str | None = None


@app.post("/api/triggers/ack/")
def ack_trigger(body: AckBody, wsid: int = Depends(current_workspace_id)):
    """Dismiss (for this workspace) a single trigger by id, or every trigger for a
    student."""
    if body.id is not None:
        n = db.ack_by_id(body.id, workspace_id=wsid)
    elif body.studentID:
        n = db.ack_by_student(body.studentID, workspace_id=wsid)
    else:
        raise HTTPException(status_code=400, detail="provide id or studentID")
    return {"acknowledged": n}


@app.get("/api/switches/")
def switches(wsid: int = Depends(current_workspace_id)):
    """Identity switches (a handle's casing flipped, or it showed up in a new
    class) detected for the students on this workspace's roster, newest first. The
    dashboard polls this for the live toast and the reviewable Switches feed."""
    items = [{
        "id": r["id"], "studentID": r["studentID"], "kind": r["kind"],
        "from": r["from_value"], "to": r["to_value"],
        "ts": _iso(db.db_to_dt(r["ts"])),
        "acknowledged": bool(r["acknowledged"]),
    } for r in db.list_switches(limit=100, workspace_id=wsid)]
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
def outbox_store(body: OutboxBody, wsid: int = Depends(current_workspace_id)):
    """Park a researcher input whose primary write failed its retries. The
    dashboard sends the original request body verbatim so nothing typed or
    clicked is ever lost -- the row can be replayed by hand later."""
    db.record_outbox(body.op,
                     json.dumps(body.payload) if body.payload is not None else None,
                     body.error, workspace_id=wsid)
    return {"stored": True}


@app.get("/api/outbox/")
def outbox_list(wsid: int = Depends(current_workspace_id)):
    """This workspace's parked failed inputs, newest first (inspection/replay)."""
    rows = db.list_outbox(workspace_id=wsid)
    return {"outbox": rows, "count": len(rows)}


class TrackBody(BaseModel):
    studentID: str | None = None
    remove: bool = False


@app.get("/api/tracked/")
def tracked_list(wsid: int = Depends(current_workspace_id)):
    rows = db.tracked_list(workspace_id=wsid)
    return {"tracked": rows, "count": len(rows)}


@app.post("/api/tracked/")
def tracked_mutate(body: TrackBody, wsid: int = Depends(current_workspace_id)):
    """Start or stop tracking a student on this workspace's board. {studentID}
    adds them (the daemon then backfills); {studentID, remove: true} untracks them
    (their shared data is purged only if no other board still tracks them)."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    if body.remove:
        db.tracked_remove(sid, workspace_id=wsid)
        return {"removed": sid}
    db.tracked_add(sid, workspace_id=wsid)
    return {"added": sid}


@app.post("/api/export/")
def export(wsid: int = Depends(current_workspace_id)):
    """Stream a CSV snapshot of THIS workspace's data as a zip the browser
    downloads. A pure read built entirely in memory; nothing is modified."""
    stamp = db.now()
    name = f"lm-dashboard_export_{stamp.strftime('%Y-%m-%d_%H%M%S')}.zip"
    return Response(
        content=db.export_zip_bytes(workspace_id=wsid),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/reset/")
def reset(wsid: int = Depends(current_workspace_id)):
    """Clear THIS workspace's researcher state for a fresh session: its notes, the
    interview-pick state (picked toggles + pick history), and its trigger
    dismissals. The roster and presence stay, and -- unlike the old single-board
    reset -- the SHARED per-student mirror is left intact (other boards depend on
    it; this board just re-derives its view). A CSV snapshot of this workspace,
    notes and picks included, is written to exports/reset_<timestamp>/ first, so
    nothing is lost. Production is never touched."""
    stamp = db.now()
    backup_dir, _ = db.export_csv(
        str(config.BASE_DIR / "exports" / f"reset_{stamp.strftime('%Y-%m-%d_%H%M%S')}"),
        workspace_id=wsid,
    )
    db.reset_workspace(workspace_id=wsid)
    return {"reset": True, "at": stamp.isoformat(), "backup": backup_dir}


def _polling_enabled(wsid) -> bool:
    """Polling is on for a workspace unless its flag is explicitly "0"; anything
    else (including a missing flag) counts as enabled."""
    return db.get_workspace_setting(wsid, "polling_enabled") != "0"


class PollingBody(BaseModel):
    enabled: bool


@app.get("/api/polling/")
def polling_status(wsid: int = Depends(current_workspace_id)):
    """Report whether the daemon is polling production for THIS workspace. The
    dashboard's pause toggle reads this to stay in sync across the board's tabs."""
    return {"enabled": _polling_enabled(wsid)}


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
def set_presence(body: PresenceBody, wsid: int = Depends(current_workspace_id)):
    """Set whether a tracked student is present in the room, on this board.
    Persisted on tracked_student, so it's included in the CSV export."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    db.set_presence(sid, body.present, workspace_id=wsid)
    return {"studentID": sid, "present": body.present}


@app.post("/api/picked/")
def set_picked(body: PickedBody, wsid: int = Depends(current_workspace_id)):
    """Set whether a tracked student has been picked/interviewed this session, on
    this board. Persisted on tracked_student (with picked_at), so it's exported."""
    sid = (body.studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    db.set_picked(sid, body.picked, source=body.source,
                  trigger_id=body.trigger_id, trigger_type=body.trigger_type,
                  workspace_id=wsid)
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
def add_note(body: NoteBody, wsid: int = Depends(current_workspace_id)):
    """Record an observation for a learner on this board. trigger_id/trigger_type
    tie it to the alert it was written from; omit both for a free-standing note.
    Persisted on the note table, so it's included in the CSV export."""
    sid = (body.studentID or "").strip()
    text = (body.text or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    return db.add_note(sid, text, body.trigger_id, body.trigger_type, workspace_id=wsid)


@app.get("/api/notes/")
def list_notes(studentID: str | None = None, wsid: int = Depends(current_workspace_id)):
    """This board's notes for a learner, in chronological order."""
    sid = (studentID or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="studentID required")
    notes = db.list_notes(sid, workspace_id=wsid)
    return {"notes": notes, "count": len(notes)}


@app.post("/api/polling/")
def set_polling(body: PollingBody, wsid: int = Depends(current_workspace_id)):
    """Pause or resume production polling for THIS workspace's students. While
    paused the daemon makes no prod requests on this board's behalf; it keeps
    running and picks back up within about a second of being re-enabled. Purely a
    control flag, prod is untouched either way."""
    db.set_workspace_setting(wsid, "polling_enabled", "1" if body.enabled else "0")
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
