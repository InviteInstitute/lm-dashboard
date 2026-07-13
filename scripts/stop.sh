#!/usr/bin/env bash
# Tear down the LM Dashboard stack that scripts/start.sh brought up: close the
# tunnel (ngrok or cloudflare, if any), free the ports, kill the processes, then report.
cd "$(dirname "$0")/.." || exit 1
echo "Stopping LM Dashboard stack ..."

# Close the tunnels first (the public doors), by pidfile then by a BROAD pattern,
# so nothing is left exposed no matter how it was launched (start.sh or by hand).
if [ -f .ngrok.pid ] && kill "$(cat .ngrok.pid)" 2>/dev/null; then echo "  closed ngrok tunnel"; fi
rm -f .ngrok.pid
pkill -f ngrok 2>/dev/null && echo "  killed ngrok"
if [ -f .cloudflared.pid ] && kill "$(cat .cloudflared.pid)" 2>/dev/null; then echo "  closed cloudflare tunnel"; fi
rm -f .cloudflared.pid
pkill -f cloudflared 2>/dev/null && echo "  killed cloudflared"

for p in 8000 3000 4000; do
  pids=$(lsof -ti tcp:$p 2>/dev/null)
  if [ -n "$pids" ]; then kill $pids 2>/dev/null && echo "  killed port $p"; fi
done
pkill -f "app.pipeline"     2>/dev/null && echo "  killed daemon"
pkill -f "mkdocs serve"     2>/dev/null && echo "  killed docs"
pkill -f "uvicorn app.main" 2>/dev/null && echo "  killed api"
sleep 1
echo "Ports now:"
for p in 8000 3000 4000; do
  if lsof -ti tcp:$p >/dev/null 2>&1; then echo "  $p STILL UP"; else echo "  $p free"; fi
done
