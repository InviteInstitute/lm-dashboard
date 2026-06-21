#!/usr/bin/env bash
# Tear down the LM Dashboard stack that scripts/start.sh brought up: free the
# three ports, kill the daemon/docs/api processes, then report what's left.
echo "Stopping LM Dashboard stack ..."
for p in 8000 3000 4000; do
  pids=$(lsof -ti tcp:$p 2>/dev/null)
  if [ -n "$pids" ]; then kill $pids 2>/dev/null && echo "  killed port $p"; fi
done
pkill -f "app.pipeline"   2>/dev/null && echo "  killed daemon"
pkill -f "mkdocs serve"   2>/dev/null && echo "  killed docs"
pkill -f "uvicorn app.main" 2>/dev/null && echo "  killed api"
sleep 1
echo "Ports now:"
for p in 8000 3000 4000; do
  if lsof -ti tcp:$p >/dev/null 2>&1; then echo "  $p STILL UP"; else echo "  $p free"; fi
done
