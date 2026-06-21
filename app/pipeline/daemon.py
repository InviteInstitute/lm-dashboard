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
from datetime import timedelta

from app import db
from app.pipeline import poller, workers, triggers
from app.pipeline.client import ProdClient, ProdClientError

log = logging.getLogger("pipeline")

# How often to re-read the pause flag while paused. It's a cheap local SQLite
# read with no prod request, kept short so a Resume click is honored within ~1s.
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

    db.init_db()  # builds the schema on a fresh DB, no-op on an existing one
    client = ProdClient()
    cursor = poller.get_cursor()

    # On a brand-new cursor, anchor it back only `backfill_hours` so the first
    # drain doesn't try to replay months of history.
    if cursor.last_event_time is None and opts.backfill_hours > 0:
        cursor.last_event_time = db.now() - timedelta(hours=opts.backfill_hours)
        cursor.save()
        log.info("seeded cursor: backfilling last %sh", opts.backfill_hours)

    log.info("Pipeline up. interval=%ss limit=%s cursor.last_event_time=%s",
             interval, limit, cursor.last_event_time)

    # Reset handshake: the API stamps meta['reset_requested_at'], and when we see
    # that value change we drop the in-memory workers so their buffered events
    # don't re-materialize the state that was just wiped. Prime last_reset with
    # the current value so an already-set flag doesn't fire a spurious reset on
    # boot.
    last_reset = db.get_meta("reset_requested_at")
    last_paused = None
    # Remembered across ticks only to log pause transitions; the disabled set is
    # re-read each tick (it changes at human speed and is cheaply cached).
    last_disabled = None

    fails = idle = 0
    while True:
        t0 = time.monotonic()
        backfilled_now = False

        # Read all three control flags in a single round-trip per tick. Their
        # cache TTL is 200ms, so a dashboard click still lands within ~200ms.
        flags = db.get_meta_many(("reset_requested_at", "polling_enabled", "disabled_triggers"))
        rr = flags["reset_requested_at"]
        paused = (flags["polling_enabled"] == "0")
        disabled = {t for t in (flags["disabled_triggers"] or "").split(",") if t}

        if rr != last_reset:
            workers.reset()
            db.reset_all()
            last_reset = rr
            log.info("reset handled (%s) — cleared in-memory workers + local data", rr)

        if paused != last_paused:
            log.info("polling %s (dashboard toggle)", "PAUSED" if paused else "RESUMED")
            last_paused = paused
        if paused:
            idle = 0  # resume responsive
            time.sleep(PAUSED_POLL_S)
            continue

        try:
            # The roster is the allowlist: we only ingest and compute the
            # students the researcher is tracking.
            roster = db.tracked_list()
            tracked = {r["studentID"] for r in roster}
            workers.reconcile(tracked)

            # A freshly-added student gets a one-time history backfill, then an
            # immediate materialize so their card fills in right away.
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
