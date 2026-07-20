#!/usr/bin/env python3
"""Follow VEX logs live: print every new event that arrives from the moment you
start this, until Ctrl+C. Nothing historical, just the stream from now on.

Reuses lm-dashboard's ProdClient, so it authenticates from .env.mirror and reads
the same /api/rabbitmq/vex_logs/ endpoint the daemon does. One JSON object per
line, so you can pipe it to a file or to `jq`.

  .venv/bin/python scripts/follow_logs.py
  .venv/bin/python scripts/follow_logs.py > live.jsonl
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.pipeline.client import ProdClient, ProdClientError  # noqa: E402

POLL_SECONDS = 5

client = ProdClient(read_timeout=30)
# The feed's recieved_at is fixed-width ISO ("...Z"), so plain string compare is
# chronological. Start the cursor at "now" in that exact format.
since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
seen = set()  # ponytail: grows over a session; fine for a live tail, reset by restarting

print(f"following new logs since {since}  (Ctrl+C to stop)", file=sys.stderr)
try:
    while True:
        try:
            rows = client.page_by_time(since, 500, 0)   # newest first
        except ProdClientError as e:
            print(f"[warn] {e}", file=sys.stderr)
            time.sleep(POLL_SECONDS)
            continue
        fresh = [r for r in rows if r.get("id") not in seen]
        for r in reversed(fresh):                        # print oldest -> newest
            seen.add(r.get("id"))
            since = max(since, r.get("recieved_at") or since)   # advance the cursor
            print(json.dumps(r, default=str), flush=True)
        time.sleep(POLL_SECONDS)
except KeyboardInterrupt:
    print("\nstopped.", file=sys.stderr)
