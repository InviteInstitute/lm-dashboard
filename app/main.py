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
import os
import time
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from learner_models import extract_workspace_xml
from log_parser_delta_engine import generate_readable_text
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import config, db, goal_evidence, zany
from app.constants import (
    TRIGGER_LABELS,
    TRIGGER_RECENT_SECONDS,
)
from app.turnstile import COOKIE_NAME, TurnstileGateMiddleware, sign_cookie, verify_turnstile

app = FastAPI(title="LM Dashboard")
# Middleware runs outermost-first in reverse add order, so these are added
# inner -> outer: GZip inside TurnstileGate (bot gate over /api/*) inside CORS
# (handles preflight). Result order: CORS -> TurnstileGate -> GZip -> routes.
#
# The SSE stream opts out of gzip via an explicit Content-Encoding so events are
# never buffered by a gzip window.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TurnstileGateMiddleware)
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


def _since_reset(runs, episodes, since):
    """The run and episode tracks cut to what happened at/after `since` (a board
    reset). Items with no timestamp are kept; a pause survives only after a kept
    episode. Returns (runs, episodes, run_count, event_count) for the payload."""
    cut = since.timestamp()
    kept_runs = [r for r in runs.get("runs") or [] if r.get("ts") is None or r["ts"] >= cut]
    eps = [
        e
        for e in (episodes or {}).get("episodes") or []
        if e.get("start_ts") is None or e["start_ts"] >= cut
    ]
    first = eps[0].get("start_idx", 0) if eps else None
    pauses = [
        p
        for p in (episodes or {}).get("pauses") or []
        if first is not None and p.get("after_idx", -1) >= first
    ]
    events = sum(e.get("event_count") or 0 for e in eps)
    return (
        {**runs, "runs": kept_runs, "run_count": len(kept_runs)},
        {
            **(episodes or {}),
            "episodes": eps,
            "pauses": pauses,
            "event_count": events,
            "episode_count": len(eps),
            "pause_count": len(pauses),
        },
        len(kept_runs),
        events,
    )


def _shown(student_id):
    """The ID a researcher knows a student by: a ZANY student's is the participant ID they typed."""
    return zany.split(student_id)[1] if zany.is_zany(student_id) else student_id


def _shape_state(s, heavy=False, since=None):
    """Turn a materialized student_state row into the dashboard's JSON payload.

    By default this is the light shape the cohort grid uses: it carries the
    per-run edit distances and episode tracks but omits the bulky playground dump. Passing
    heavy=True adds `block`, the large playground_prompt tree, which only the
    detail modal renders, so it's fetched one student at a time on open instead
    of for the whole cohort on every poll. `since` (this board's last reset)
    hides the runs and episodes from before it, so the tile starts fresh."""
    out = {
        "studentID": s["studentID"],
        "display": _shown(s.get("display_id") or s["studentID"]),  # most-recent casing for the UI
        "classCode": s["classCode"],
        "run_count": s["run_count"],
        "event_count": s["event_count"],
        "last_seen": _iso(s["last_event_time"]),
        "runs": s["runs"] or {},  # {runs:[{index,edit_distance,ts}], run_count}
        "episodes": s["episodes"],  # {events, episodes, pauses,...}
        "updated_at": _iso(s["updated_at"]),
    }
    if since is not None:
        out["runs"], out["episodes"], out["run_count"], out["event_count"] = _since_reset(
            out["runs"], out["episodes"], since
        )
    if heavy:
        out["block"] = {
            "llm_prompt": s["playground_prompt"],
            "timestamp": _iso(s["playground_time"]),
        }
    return out


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
def _client_ip(request):
    """The browser's address: the first X-Forwarded-For hop (nginx sets it), else the peer."""
    return (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (
        request.client.host if request.client else ""
    )


def _required(value, name):
    """A required text field, trimmed. A missing or blank one is a 400."""
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{name} required")
    return value


@app.get("/healthz")
def health():
    # Not at "/" so the static frontend mount can serve the dashboard there.
    return {"service": "luc-dashboard", "ok": True}


# --------------------------------------------------------------------------
# bot gate: /api/* is behind Cloudflare Turnstile (see app/turnstile.py). This
# is the one route TurnstileGateMiddleware leaves open so a browser can solve
# the widget and get the cookie the middleware then checks on every other call.
# --------------------------------------------------------------------------
class TurnstileVerifyRequest(BaseModel):
    token: str


@app.post("/api/turnstile/verify/")
async def turnstile_verify(body: TurnstileVerifyRequest, request: Request, response: Response):
    if not await verify_turnstile(body.token, _client_ip(request)):
        raise HTTPException(status_code=403, detail="turnstile verification failed")
    response.set_cookie(
        COOKIE_NAME,
        sign_cookie(),
        max_age=12 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"ok": True}


# --------------------------------------------------------------------------
# sources: each board listens to Reflecks (VEXcode VR) or to one ZANY study
# --------------------------------------------------------------------------
# ZANY's logs come from ATLAS-invite's store (app/zany.py) and are for the research team only:
# a browser unlocks them with the research login, which ATLAS checks, for UNLOCK_HOURS. A board
# set to a ZANY study answers nothing until its browser is unlocked.
REFLECKS = "reflecks"
UNLOCK_COOKIE = "zany_unlocked"
UNLOCK_HOURS = 12
UNLOCK_TRIES = 5  # wrong logins a browser may try ...
UNLOCK_WINDOW = 600  # ... in this many seconds
_unlock_signer = TimestampSigner(config.SESSION_SECRET, salt="zany-unlock")
_unlock_failures: dict[str, list[float]] = {}


def zany_unlocked(request: Request) -> bool:
    value = request.cookies.get(UNLOCK_COOKIE)
    if not value:
        return False
    try:
        _unlock_signer.unsign(value, max_age=UNLOCK_HOURS * 3600)
        return True
    except (BadSignature, SignatureExpired):
        return False


def board_source(wsid):
    return db.get_workspace_setting(wsid, "source") or REFLECKS


def _in_source(student_id, source):
    """Whether a student belongs on a board listening to `source`."""
    sid = db.canon_id(student_id)
    if source.startswith(zany.PREFIX):
        return sid.startswith(db.canon_id(source) + ":")
    return not zany.is_zany(sid)


async def current_workspace_id(request: Request) -> int:
    """The workspace this request acts in, so every data route scopes to the
    caller's own board. Prefers the per-browser board the SPA names via the
    X-Board-Id header (or a ?board_id= query param on the SSE stream, which can't
    send headers); otherwise falls back to a single shared workspace for
    headerless (non-browser) clients. Cached on request.state."""
    cached = getattr(request.state, "workspace_id", None)
    if cached is not None:
        return cached
    board = request.headers.get("X-Board-Id") or request.query_params.get("board_id")
    if board:
        wsid = await run_in_threadpool(db.workspace_for_client_key, board)
    else:
        wsid = await run_in_threadpool(db.default_workspace_id)
    # A board on a ZANY study needs an unlocked browser for everything but changing its
    # source or unlocking.
    path = request.url.path
    if not path.startswith(("/api/source/", "/api/zany/")):
        source = await run_in_threadpool(board_source, wsid)
        if source != REFLECKS and not zany_unlocked(request):
            raise HTTPException(status_code=403, detail="zany_locked")
    request.state.workspace_id = wsid
    return wsid


class UnlockBody(BaseModel):
    email: str
    password: str


class SourceBody(BaseModel):
    source: str


def _studies():
    try:
        return zany.studies()
    except Exception as e:  # the store is down or unreachable: say so, keep Reflecks working
        raise HTTPException(status_code=503, detail="ZANY's log store isn't answering.") from e


@app.get("/api/zany/")
def zany_status(request: Request):
    """Whether ZANY's logs can be read here, whether this browser has unlocked them, and the
    studies with records once it has."""
    unlocked = zany.enabled() and zany_unlocked(request)
    return {
        "enabled": zany.enabled(),
        "unlocked": unlocked,
        "studies": _studies() if unlocked else [],
    }


@app.post("/api/zany/unlock/")
def zany_unlock(body: UnlockBody, request: Request, response: Response):
    """Unlock ZANY's logs in this browser with the research login, which ATLAS checks."""
    if not zany.enabled():
        raise HTTPException(status_code=404, detail="ZANY's logs aren't connected here.")
    ip, now = _client_ip(request), time.monotonic()
    recent = [t for t in _unlock_failures.get(ip, []) if now - t < UNLOCK_WINDOW]
    if len(recent) >= UNLOCK_TRIES:
        raise HTTPException(status_code=429, detail="Too many tries. Wait ten minutes.")
    try:
        zany.researcher_login(body.email.strip(), body.password)
    except zany.LoginFailed as e:
        _unlock_failures[ip] = [*recent, now]
        raise HTTPException(status_code=401, detail=str(e)) from e
    _unlock_failures.pop(ip, None)
    response.set_cookie(
        UNLOCK_COOKIE,
        _unlock_signer.sign(b"ok").decode(),
        max_age=UNLOCK_HOURS * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"unlocked": True, "studies": _studies()}


@app.post("/api/zany/lock/")
def zany_lock(response: Response):
    response.delete_cookie(UNLOCK_COOKIE)
    return {"unlocked": False}


@app.get("/api/zany/participants/")
def zany_participants(study: str, request: Request):
    """The participant IDs with records in one study, for "Track everyone"."""
    if not zany_unlocked(request):
        raise HTTPException(status_code=403, detail="zany_locked")
    try:
        return {"participants": zany.participants(study)}
    except Exception as e:
        raise HTTPException(status_code=503, detail="ZANY's log store isn't answering.") from e


@app.get("/api/source/")
def source_get(wsid: int = Depends(current_workspace_id)):
    return {"source": board_source(wsid)}


@app.post("/api/source/")
def source_set(body: SourceBody, request: Request, wsid: int = Depends(current_workspace_id)):
    """Point this board at Reflecks or at one ZANY study (`zany:<study>`)."""
    source = body.source.strip()
    if source != REFLECKS:
        if not source.startswith(zany.PREFIX) or not zany.enabled():
            raise HTTPException(status_code=400, detail="Unknown source.")
        if not zany_unlocked(request):
            raise HTTPException(status_code=403, detail="zany_locked")
        if source[len(zany.PREFIX) :] not in {s["study"] for s in _studies()}:
            raise HTTPException(status_code=400, detail="No such study with records.")
    db.set_workspace_setting(wsid, "source", source)
    return {"source": source}


@app.get("/api/student_states/")
def student_states(classCode: str | None = None, wsid: int = Depends(current_workspace_id)):
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
    since = db.reset_since(wsid)
    source = board_source(wsid)
    rows = [
        _shape_state(s, since=since)
        for s in db.list_student_states(class_code=classCode, workspace_id=wsid)
        if _in_source(s["studentID"], source)
    ]
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
STREAM_TICK_SECONDS = 0.25  # how often to read the change fingerprint (a few tiny rows)
STREAM_HEARTBEAT_TICKS = 40  # stamp presence + send a keepalive comment every N ticks (~10s)


def _changed_channels(prev, cur):
    """Channel names whose fingerprint changed between two snapshots. Pure and
    I/O-free so it can be unit-tested; `prev is None` (the first tick) is never a
    change."""
    if prev is None:
        return []
    return [name for name in cur if cur.get(name) != prev.get(name)]


@app.get("/api/stream/")
async def stream(request: Request, once: bool = False, wsid: int = Depends(current_workspace_id)):
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
        await run_in_threadpool(
            db.set_workspace_setting, wsid, "viewer_last_seen", db.now().isoformat()
        )
        ticks = 0
        while not await request.is_disconnected():
            await asyncio.sleep(STREAM_TICK_SECONDS)
            cur = await run_in_threadpool(db.data_fingerprint)
            changed = _changed_channels(prev, cur)
            if changed:
                prev = cur
                yield f"event: changed\ndata: {json.dumps({'channels': changed})}\n\n"
            ticks += 1
            if ticks % STREAM_HEARTBEAT_TICKS == 0:
                await run_in_threadpool(
                    db.set_workspace_setting, wsid, "viewer_last_seen", db.now().isoformat()
                )
                yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # Pre-set encoding: GZipMiddleware skips responses that already
            # carry one, so events are never buffered inside a gzip window.
            "Content-Encoding": "identity",
        },
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
    since = db.reset_since(wsid)
    payload = _shape_state(rows[0], heavy=True, since=since)
    # Readable program listing (feature #12): the student's latest blocks with
    # their parameters spelled out, incl. the numbers the edit-distance AST drops.
    # Best-effort and isolated -- a parse miss just yields "".
    proj = db.latest_project(student_id)
    payload["block"]["readable"] = (
        generate_readable_text(extract_workspace_xml({"project": proj})) if proj else ""
    )
    # Real-time goal evidence (with uncertainty), one entry per profiled run.
    # Best-effort and isolated -- absent or failing, the detail view just omits it.
    payload["goal_recognition_enabled"] = config.GOAL_RECOGNITION_ENABLED
    try:
        payload["goal_runs"] = goal_evidence.goal_runs(student_id, since=since)
    except Exception:
        payload["goal_runs"] = []
    return payload


@app.get("/api/triggers/")
def triggers(wsid: int = Depends(current_workspace_id)):
    """The intervention feed for this workspace: still-open triggers on its roster
    plus any resolved within the last TRIGGER_RECENT_SECONDS, newest first, that
    this workspace hasn't dismissed, of the types it hasn't switched off."""
    now = db.now()
    cutoff = now - timedelta(seconds=TRIGGER_RECENT_SECONDS)
    since = db.reset_since(wsid)
    source = board_source(wsid)
    hidden = _disabled_triggers(wsid)
    feed = [
        t
        for t in db.triggers_feed(cutoff, workspace_id=wsid, since=since)
        if _in_source(t["studentID"], source) and t["trigger_type"] not in hidden
    ]
    # Each alert also carries the student's PREVIOUS trigger (what and when), so
    # the card can say "Before this: Wheel-spinning at 10:24 AM". One history fetch per
    # distinct student in the feed; the feed is small, so this stays cheap.
    history = {
        sid: db.trigger_history(sid, workspace_id=wsid, since=since)
        for sid in {t["studentID"] for t in feed}
    }
    items, counts = [], {}
    for t in feed:
        active = t["resolved_at"] is None
        d = t["detail"] or {}
        started = t["started_at"]
        prev = next(
            (
                h
                for h in history[t["studentID"]]
                if h["id"] != t["id"] and h["started_at"] and started and h["started_at"] <= started
            ),
            None,
        )
        pd = (prev or {}).get("detail") or {}
        items.append(
            {
                "id": t["id"],
                "studentID": t["studentID"],
                "trigger_type": t["trigger_type"],
                "label": d.get("label", t["trigger_type"]),
                "value": d.get("value"),
                "started_at": _iso(started),
                "resolved_at": _iso(t["resolved_at"]),
                "active": active,
                "age_seconds": (now - started).total_seconds() if started else None,
                "prev": {
                    "trigger_type": prev["trigger_type"],
                    "label": pd.get("label", prev["trigger_type"]),
                    "at": _iso(prev["started_at"]),
                }
                if prev
                else None,
            }
        )
        if active:
            counts[t["trigger_type"]] = counts.get(t["trigger_type"], 0) + 1
    return {
        "triggers": items,
        "active_count": sum(1 for i in items if i["active"]),
        "counts": counts,
    }


@app.get("/api/triggers/history/")
def trigger_history(studentID: str, wsid: int = Depends(current_workspace_id)):
    """One student's full trigger history, newest first -- open, resolved, and
    dismissed alike -- with this workspace's dismiss state. The detail modal
    renders this as the trigger-history grid."""
    if not studentID:
        raise HTTPException(status_code=400, detail="provide studentID")
    rows = []
    for t in db.trigger_history(studentID, workspace_id=wsid, since=db.reset_since(wsid)):
        d = t["detail"] or {}
        rows.append(
            {
                "id": t["id"],
                "trigger_type": t["trigger_type"],
                "label": d.get("label", t["trigger_type"]),
                "value": d.get("value"),
                "started_at": _iso(t["started_at"]),
                "resolved_at": _iso(t["resolved_at"]),
                "status": (
                    "dismissed"
                    if t["acknowledged"]
                    else "active"
                    if t["resolved_at"] is None
                    else "resolved"
                ),
            }
        )
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
    items = [
        {
            "id": r["id"],
            "studentID": r["studentID"],
            "kind": r["kind"],
            "from": r["from_value"],
            "to": r["to_value"],
            "ts": _iso(r["ts"]),
            "acknowledged": bool(r["acknowledged"]),
        }
        for r in db.list_switches(limit=100, workspace_id=wsid, since=db.reset_since(wsid))
        if _in_source(r["studentID"], board_source(wsid))
    ]
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
    db.record_outbox(
        body.op,
        json.dumps(body.payload) if body.payload is not None else None,
        body.error,
        workspace_id=wsid,
    )
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
    source = board_source(wsid)
    rows = [
        {**r, "display": _shown(r["display"])}
        for r in db.tracked_list(workspace_id=wsid)
        if _in_source(r["studentID"], source)
    ]
    return {"tracked": rows, "count": len(rows), "source": source}


@app.post("/api/tracked/")
def tracked_mutate(body: TrackBody, wsid: int = Depends(current_workspace_id)):
    """Start or stop tracking a student on this workspace's board. {studentID}
    adds them (the daemon then backfills); {studentID, remove: true} untracks them
    (their shared data is purged only if no other board still tracks them)."""
    sid = _required(body.studentID, "studentID")
    if body.remove:
        db.tracked_remove(sid, workspace_id=wsid)
        return {"removed": sid}
    # On a ZANY board, an ID typed is a participant ID in that board's study.
    source = board_source(wsid)
    if source.startswith(zany.PREFIX) and not zany.is_zany(sid):
        sid = zany.key(source[len(zany.PREFIX) :], sid)
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
    """Start THIS workspace fresh: clear its notes, the interview-pick state
    (picked toggles + pick history) and its trigger dismissals, and from now on
    show only activity after this moment on every part of the student tile (runs,
    episodes, goal evidence, alerts, trigger history, switches). The roster and
    presence stay, and the SHARED per-student mirror is left intact (other boards
    depend on it). This board just reads it from the reset on. The same zip the
    Export button gives, notes and picks included, is saved to
    exports/reset_<timestamp>.zip first, so nothing is lost. Production is never
    touched."""
    stamp = db.now()
    backup = config.BASE_DIR / "exports" / f"reset_{stamp.strftime('%Y-%m-%d_%H%M%S')}.zip"
    backup.parent.mkdir(exist_ok=True)
    backup.write_bytes(db.export_zip_bytes(workspace_id=wsid))
    db.reset_workspace(workspace_id=wsid)
    return {"reset": True, "at": stamp.isoformat(), "backup": str(backup)}


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
    source: str = "roster"  # 'roster' | 'intervention'
    trigger_id: int | None = None  # set only for intervention picks
    trigger_type: str | None = None


@app.post("/api/presence/")
def set_presence(body: PresenceBody, wsid: int = Depends(current_workspace_id)):
    """Set whether a tracked student is present in the room, on this board.
    Persisted on tracked_student, so it's included in the CSV export."""
    sid = _required(body.studentID, "studentID")
    db.set_presence(sid, body.present, workspace_id=wsid)
    return {"studentID": sid, "present": body.present}


@app.post("/api/picked/")
def set_picked(body: PickedBody, wsid: int = Depends(current_workspace_id)):
    """Set whether a tracked student has been picked/interviewed this session, on
    this board. Persisted on tracked_student (with picked_at), so it's exported."""
    sid = _required(body.studentID, "studentID")
    db.set_picked(
        sid,
        body.picked,
        source=body.source,
        trigger_id=body.trigger_id,
        trigger_type=body.trigger_type,
        workspace_id=wsid,
    )
    return {"studentID": sid, "picked": body.picked}


TRIGGER_TYPES = tuple(TRIGGER_LABELS)


def _disabled_triggers(wsid) -> set[str]:
    """The trigger types this board has switched off. A board that never set its
    own keeps the shared setting from before the switches were per board."""
    raw = db.get_workspace_setting(wsid, "disabled_triggers")
    if raw is None:
        raw = db.get_meta("disabled_triggers") or ""
    return {t for t in raw.split(",") if t}


class TriggerConfigBody(BaseModel):
    trigger_type: str
    enabled: bool


@app.get("/api/triggers/config/")
def triggers_config(wsid: int = Depends(current_workspace_id)):
    """Which trigger types this board shows (all on by default), with their
    display labels."""
    disabled = _disabled_triggers(wsid)
    return {
        "enabled": {t: (t not in disabled) for t in TRIGGER_TYPES},
        "labels": TRIGGER_LABELS,
    }


@app.post("/api/triggers/config/")
def set_triggers_config(body: TriggerConfigBody, wsid: int = Depends(current_workspace_id)):
    """Show or hide one trigger type on this board. The daemon keeps firing every
    type, since alerts are shared by all boards, so this only filters this board's
    feed: switching a type back on brings back its alerts that are still current."""
    if body.trigger_type not in TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail="unknown trigger_type")
    disabled = _disabled_triggers(wsid)
    if body.enabled:
        disabled.discard(body.trigger_type)
    else:
        disabled.add(body.trigger_type)
    db.set_workspace_setting(wsid, "disabled_triggers", ",".join(sorted(disabled)))
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
    sid = _required(body.studentID, "studentID")
    text = _required(body.text, "text")
    return db.add_note(sid, text, body.trigger_id, body.trigger_type, workspace_id=wsid)


@app.get("/api/notes/")
def list_notes(studentID: str | None = None, wsid: int = Depends(current_workspace_id)):
    """This board's notes for a learner, in chronological order."""
    sid = _required(studentID, "studentID")
    notes = db.list_notes(sid, workspace_id=wsid)
    return {"notes": notes, "count": len(notes)}


@app.post("/api/polling/")
def set_polling(body: PollingBody, wsid: int = Depends(current_workspace_id)):
    """Pause or resume production polling for THIS workspace's students. While
    paused the daemon makes no prod requests on this board's behalf; it keeps
    running and picks back up within about a second of being re-enabled. Purely a
    control flag, prod is untouched either way."""
    was_enabled = _polling_enabled(wsid)
    db.set_workspace_setting(wsid, "polling_enabled", "1" if body.enabled else "0")
    if body.enabled and not was_enabled:
        # Refill the pause gap: backfill is idempotent, and the daemon rebuilds
        # each student's worker from the log afterwards.
        db.mark_workspace_for_backfill(wsid)
    return {"enabled": body.enabled}


# --------------------------------------------------------------------------
# static frontend
# --------------------------------------------------------------------------
# Serve the built React app (frontend/dist) at the root, so the UI and /api share
# one origin behind nginx: no second service, no CORS. Mounted last, after every
# /api route, so it never shadows them, and only when a build exists, so local
# development with Vite on :3000 is unaffected.
_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="spa")
