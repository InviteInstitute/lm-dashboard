"""
Single-writer ingestion + inference daemon.

    python -m app.pipeline [--interval 0.5] [--limit 500] [--backfill-hours 0]

Each tick: drain prod into raw logs (idempotent, cursor-advanced), run inference
on the workers whose state changed and materialize student_state, then evaluate
triggers. Run exactly ONE instance (it is the only writer); cursor + idempotency
make a crash-restart lossless. Needs prod creds (.env.mirror or env).
"""
import argparse
import logging
import os
import random
import time
from datetime import timedelta

from app import db
from app.pipeline import poller, workers, triggers
from app.pipeline.client import ProdClient, ProdClientError

log = logging.getLogger("pipeline")

# While paused, re-check the local pause flag this often (cheap SQLite read, no
# prod request) so a Resume click takes effect within ~1s.
PAUSED_POLL_S = 1.0


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="VEX ingestion + inference pipeline (single writer).")
    p.add_argument("--interval", type=float,
                   default=float(os.environ.get("PIPELINE_INTERVAL", 0.5)),
                   help="Base seconds per tick while events are flowing (default 0.5).")
    p.add_argument("--idle-max", type=float,
                   default=float(os.environ.get("PIPELINE_IDLE_MAX", 5.0)),
                   help="Ceiling for the idle backoff: when nothing is happening, "
                        "poll intervals grow toward this (default 5s) to stop "
                        "hammering prod with empty polls.")
    p.add_argument("--limit", type=int,
                   default=int(os.environ.get("PIPELINE_PAGE_LIMIT", 500)),
                   help="Events per page when draining (default 500).")
    p.add_argument("--overlap", type=float, default=2.0,
                   help="Cursor overlap seconds to absorb same-ts straddles.")
    p.add_argument("--backfill-hours", type=float,
                   default=float(os.environ.get("PIPELINE_BACKFILL_HOURS", 24)),
                   help="On first run (empty cursor) only backfill the last N hours "
                        "(default 24, <=0 = replay all history). Bounds the initial drain.")
    return p.parse_args(argv)


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )
    opts = _parse_args(argv)
    interval, limit, overlap, idle_max = opts.interval, opts.limit, opts.overlap, opts.idle_max

    db.init_db()  # no-op on the existing DB; creates tables on a fresh one
    client = ProdClient()
    cursor = poller.get_cursor()

    # Seed an empty cursor so a fresh start doesn't replay months of history.
    if cursor.last_event_time is None and opts.backfill_hours > 0:
        cursor.last_event_time = db.now() - timedelta(hours=opts.backfill_hours)
        cursor.save()
        log.info("seeded cursor: backfilling last %sh", opts.backfill_hours)

    log.info("Pipeline up. interval=%ss limit=%s cursor.last_event_time=%s",
             interval, limit, cursor.last_event_time)

    # Reset signal: the API stamps meta['reset_requested_at']; we drop in-memory
    # workers (so buffered events don't re-materialize) when it changes. Prime it
    # to the current value so a stale flag doesn't fire a reset on boot.
    last_reset = db.get_meta("reset_requested_at")
    last_paused = None

    fails = idle = 0
    while True:
        t0 = time.monotonic()
        backfilled_now = False

        rr = db.get_meta("reset_requested_at")
        if rr != last_reset:
            workers.reset()
            db.reset_all()
            last_reset = rr
            log.info("reset handled (%s) — cleared in-memory workers + local data", rr)

        # Polling pause switch (dashboard button). When paused, make ZERO prod
        # requests: skip backfill + drain + inference entirely and idle locally
        # until re-enabled. Reset (above) is still honored while paused.
        paused = db.get_meta("polling_enabled") == "0"
        if paused != last_paused:
            log.info("polling %s (dashboard toggle)", "PAUSED" if paused else "RESUMED")
            last_paused = paused
        if paused:
            idle = 0  # resume responsive
            time.sleep(PAUSED_POLL_S)
            continue

        try:
            # roster: only ingest + compute the studentIDs the user tracks
            roster = db.tracked_list()
            tracked = {r["studentID"] for r in roster}
            workers.reconcile(tracked)

            # newly-added students: backfill their history once, materialize now
            for r in roster:
                if not r["backfilled"]:
                    try:
                        poller.backfill_student(client, r["studentID"])
                        workers.get_worker(r["studentID"]).recompute_and_write()
                        db.mark_backfilled(r["studentID"])
                        backfilled_now = True
                        log.info("backfilled + materialized %s", r["studentID"])
                    except Exception as e:
                        log.warning("backfill failed for %s: %s", r["studentID"], e)

            new = poller.drain(client, cursor, limit=limit, overlap_seconds=overlap,
                               tracked=tracked)
            fails = 0
        except ProdClientError as e:   # transient: 504/timeout/auth/etc.
            fails += 1
            delay = min(30.0, 0.5 * (2 ** min(fails, 6))) + random.uniform(0, 0.5)
            log.warning("drain failed (%d): %s -- backoff %.1fs", fails, e, delay)
            if fails >= 5:
                log.error("UNHEALTHY: %d consecutive poll failures", fails)
            time.sleep(delay)
            continue
        except Exception:
            # Not a known-transient prod error -- this is almost certainly a bug
            # in our own code. Don't perpetually back off and hide it: log and
            # re-raise so the process supervisor restarts (and the error stays
            # visible) instead of silently sleeping in a loop.
            log.exception("daemon tick crashed on a non-transient error -- exiting")
            raise

        # Inference clock: run on changed workers, materialize state.
        changed = workers.dirty_workers()
        for w in changed:
            try:
                w.recompute_and_write()
            except Exception as e:
                log.exception("inference failed for %s: %s", w.student_id, e)

        # Trigger clock: evaluate rules over ALL students (inactivity needs
        # students who aren't producing events).
        try:
            triggers.evaluate()
        except Exception as e:
            log.exception("trigger eval failed: %s", e)

        # Idle backoff: poll at the base interval while events flow; when a tick
        # does nothing, exponentially grow the wait toward --idle-max so we stop
        # hammering prod with empty polls. Any activity snaps back to responsive.
        busy = bool(new or changed or backfilled_now)
        idle = 0 if busy else idle + 1
        target = interval if busy else min(idle_max, interval * (2 ** min(idle, 6)))

        if busy:
            log.info("tick: +%d new, %d students updated, lag=%s",
                     new, len(changed), poller.get_cursor_lag(cursor))

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, target - elapsed))


if __name__ == "__main__":
    main()
