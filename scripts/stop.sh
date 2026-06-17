#!/usr/bin/env bash
# Stop the LM Dashboard stack started by scripts/start.sh.
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
