"""
The ingestion + inference daemon. This is the system's single writer.

    python -m app.pipeline [--interval 0.5] [--limit 500] [--backfill-hours 0]

It runs one blocking loop. Each tick drains new events from prod into the raw
log (idempotently, advancing a cursor), re-runs inference for the students whose
state changed and writes the result into student_state, then evaluates the
intervention triggers. Run exactly ONE instance, since the cursor and the
idempotency logic both assume a single writer; together they make a
crash-and-restart lossless. Needs prod credentials (from .env.mirror or the
environment).
"""

import argparse
import logging
import os
import random
import time
from datetime import datetime, timedelta

from app import db, zany
from app.constants import PAUSED_POLL_S, VIEWER_PRESENT_SECONDS  # pause cadence + dead-man's window
from app.pipeline import poller, triggers, workers, zany_source
from app.pipeline.client import ProdClient, ProdClientError

log = logging.getLogger("pipeline")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="VEX ingestion + inference pipeline (single writer).")
    p.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("PIPELINE_INTERVAL", 0.5)),
        help="Base seconds per tick while events are flowing (default 0.5).",
    )
    p.add_argument(
        "--idle-max",
        type=float,
        default=float(os.environ.get("PIPELINE_IDLE_MAX", 5.0)),
        help="Ceiling for the idle backoff: when nothing is happening, "
        "poll intervals grow toward this (default 5s) to stop "
        "hammering prod with empty polls.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("PIPELINE_PAGE_LIMIT", 500)),
        help="Events per page when draining (default 500).",
    )
    p.add_argument(
        "--overlap",
        type=float,
        default=2.0,
        help="Cursor overlap seconds to absorb same-ts straddles.",
    )
    p.add_argument(
        "--require-viewer",
        action="store_true",
        default=os.environ.get("PIPELINE_REQUIRE_VIEWER", "") not in ("", "0"),
        help="Dead-man's switch: only poll prod while a dashboard is "
        "open. The read API stamps viewer_last_seen on each grid "
        "poll; prod polling auto-pauses after VIEWER_PRESENT_SECONDS "
        "with no dashboard activity and resumes when one returns. "
        "Off by default; meant for served/remote sessions.",
    )
    p.add_argument(
        "--backfill-hours",
        type=float,
        default=float(os.environ.get("PIPELINE_BACKFILL_HOURS", 24)),
        help="On first run (empty cursor) only backfill the last N hours "
        "(default 24, <=0 = replay all history). Bounds the initial drain.",
    )
    return p.parse_args(argv)


def _live_workspace_ids(states, require_viewer, now):
    """Ids of the workspaces the daemon should poll prod for right now: polling
    enabled and, when --require-viewer is on, a dashboard seen within
    VIEWER_PRESENT_SECONDS. `states` is db.workspace_polling_states()."""
    live = []
    for ws in states:
        if ws["polling_enabled"] == "0":
            continue
        if require_viewer:
            seen = ws["viewer_last_seen"]
            fresh = (
                bool(seen)
                and (now - datetime.fromisoformat(seen)).total_seconds() <= VIEWER_PRESENT_SECONDS
            )
            if not fresh:
                continue
        live.append(ws["id"])
    return live


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )
    opts = _parse_args(argv)
    interval, limit, overlap, idle_max = opts.interval, opts.limit, opts.overlap, opts.idle_max
    require_viewer = opts.require_viewer

    db.init_db()  # builds the schema on a fresh DB, no-op on an existing one
    client = ProdClient()
    cursor = poller.get_cursor()

    # On a brand-new cursor, anchor it back only `backfill_hours` so the first
    # drain doesn't try to replay months of history.
    if cursor.last_event_time is None and opts.backfill_hours > 0:
        cursor.last_event_time = db.now() - timedelta(hours=opts.backfill_hours)
        cursor.save()
        log.info("seeded cursor: backfilling last %sh", opts.backfill_hours)

    log.info(
        "Pipeline up. interval=%ss limit=%s cursor.last_event_time=%s",
        interval,
        limit,
        cursor.last_event_time,
    )

    # Fan-out model: the daemon is still the single writer, but it now serves
    # every workspace at once. It ingests the UNION of all boards' rosters (one
    # shared mirror per student) and polls prod only for students on a LIVE board
    # (polling enabled and, with --require-viewer, a fresh viewer). Reset is now a
    # per-workspace API action that never touches the shared mirror, so there is
    # no reset handshake here any more.
    last_live = None  # tracks live/paused transitions for logging

    # Session cutoff: only ingest events at/after the moment this daemon started,
    # for both the per-student backfill and the live drain. That's what keeps a
    # student ID reused on a later day from pulling in their earlier sessions.
    session_start = db.now()
    log.info("session cutoff: ingesting events from %s onward", session_start)

    # Hide any prior session without deleting it: workers rehydrate from
    # session-only events, and we re-materialize every tracked student now so their
    # card reads empty at startup (the raw vex_log stays intact and recoverable).
    # ZANY (app/zany.py): rebuild every ZANY student from ATLAS's store, so nothing ATLAS
    # deleted while the daemon was down survives; start the cursor at the newest row (tracked
    # students are backfilled on their own); listen for ATLAS's notifications.
    zcursor = listener = None
    if zany.enabled():
        db.forget_all_zany()
        zcursor = zany_source.get_cursor()
        if not zcursor.last_source_id:
            with zany.connect() as con:
                zcursor.last_source_id = zany.max_seq(con)
            zcursor.save()
        listener = zany.Listener()
        log.info("ZANY source on, from store row %s", zcursor.last_source_id)

    def pause(seconds):
        """Sleep until the next tick, waking at once when ATLAS says ZANY records were kept
        or deleted. Deleted ones drop the student's mirror and models at once; they are
        backfilled again from what the store still has."""
        if listener is None:
            time.sleep(seconds)
            return
        for channel, who in listener.wait(seconds):
            if channel == zany.FORGOTTEN:
                sid = zany.key(who["study"], who["participant"])
                db.forget_student(sid)
                workers.evict(sid)
                log.info("ZANY records deleted for a student; their models are rebuilt")

    workers.start_session(session_start)
    for r in db.tracked_union():
        try:
            workers.get_worker(r["studentID"]).recompute_and_write()
        except Exception as e:
            log.warning("startup re-materialize failed for %s: %s", r["studentID"], e)

    fails = idle = 0
    while True:
        t0 = time.monotonic()
        backfilled_now = False
        new = znew = 0
        backoff = 0.0

        # disabled_triggers stays a global setting (which alert TYPES are active);
        # polling on/off and viewer presence are per-workspace. Compute the live
        # boards and the union of their rosters -- that's the prod-poll allowlist.
        disabled = {t for t in (db.get_meta("disabled_triggers") or "").split(",") if t}
        now = db.now()
        live_ids = _live_workspace_ids(db.workspace_polling_states(), require_viewer, now)
        active_tracked = db.students_in_workspaces(live_ids)

        live = bool(live_ids)
        if live != last_live:
            log.info(
                "prod polling %s (%d live workspace(s), %d student(s))",
                "RESUMED" if live else "PAUSED",
                len(live_ids),
                len(active_tracked),
            )
            last_live = live
        if not live_ids:  # no board wants polling right now
            idle = 0  # resume responsive
            pause(PAUSED_POLL_S)
            continue

        try:
            # Keep a worker for every tracked student (the union across all boards)
            # so a board whose polling is paused still shows already-ingested data;
            # but only poll prod for students on a LIVE board.
            union = db.tracked_union()
            all_tracked = {r["studentID"] for r in union}
            workers.reconcile(all_tracked)

            # A freshly-added student on a live board gets a one-time, shared
            # history backfill (once per student), then an immediate materialize.
            for r in union:
                if r["backfilled"] or r["studentID"] not in active_tracked:
                    continue
                if zany.is_zany(r["studentID"]) and zcursor is None:
                    continue  # a ZANY student, but this deployment cannot reach the store
                try:
                    if zany.is_zany(r["studentID"]):
                        zany_source.backfill_student(r["studentID"], since=session_start)
                    else:
                        poller.backfill_student(client, r["studentID"], since=session_start)
                    # Backfill only stores the history (prod pages it newest-first);
                    # rebuild the worker from the log so runs replay oldest-first.
                    workers.evict(r["studentID"])
                    workers.get_worker(r["studentID"]).recompute_and_write()
                    db.mark_backfilled(r["studentID"])
                    backfilled_now = True
                    log.info("backfilled + materialized %s", r["studentID"])
                except Exception as e:
                    log.warning("backfill failed for %s: %s", r["studentID"], e)

            if zcursor is not None:
                try:
                    znew = zany_source.drain(zcursor, active_tracked, since=session_start)
                except Exception as e:  # the store or the network; Reflecks carries on
                    log.warning("ZANY drain failed: %s", e)
            new = poller.drain(
                client,
                cursor,
                limit=limit,
                overlap_seconds=overlap,
                tracked=active_tracked,
                since=session_start,
            )
            fails = 0
        except ProdClientError as e:  # transient: 504/timeout/auth/etc.
            fails += 1
            delay = min(30.0, 0.5 * (2 ** min(fails, 6))) + random.uniform(0, 0.5)
            log.warning("drain failed (%d): %s -- backoff %.1fs", fails, e, delay)
            if fails >= 5:
                log.error("UNHEALTHY: %d consecutive poll failures", fails)
            # Back off from Reflecks, but still model what ZANY brought in this tick.
            new, backoff = 0, delay
        except Exception:
            # Anything that isn't a known-transient prod error is almost
            # certainly a bug on our side. Backing off would just hide it in a
            # silent sleep loop, so instead we log it and re-raise, letting the
            # process supervisor restart us with the error still visible.
            log.exception("daemon tick crashed on a non-transient error -- exiting")
            raise

        # Inference: recompute only the workers that took new events this tick,
        # writing each result into student_state.
        changed = workers.dirty_workers()
        for w in changed:
            try:
                w.recompute_and_write(disabled=disabled)
            except Exception as e:
                log.exception("inference failed for %s: %s", w.student_id, e)

        # Triggers: sweep over EVERY student, not just the changed ones, because
        # inactivity is about students who have stopped producing events.
        try:
            triggers.evaluate(disabled=disabled)
        except Exception as e:
            log.exception("trigger eval failed: %s", e)

        # Idle backoff: while events are flowing, sleep the base interval; once a
        # tick finds nothing to do, grow the wait exponentially toward --idle-max
        # so quiet stretches don't keep hammering prod with empty polls. The
        # first sign of activity snaps the interval straight back to responsive.
        busy = bool(new or znew or changed or backfilled_now)
        idle = 0 if busy else idle + 1
        target = interval if busy else min(idle_max, interval * (2 ** min(idle, 6)))

        if busy:
            log.info(
                "tick: +%d new, %d students updated, lag=%s",
                new,
                len(changed),
                poller.get_cursor_lag(cursor),
            )

        elapsed = time.monotonic() - t0
        pause(max(backoff, target - elapsed))


if __name__ == "__main__":
    main()
