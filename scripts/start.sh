#!/usr/bin/env bash
# Start the LM Dashboard stack:
#   read API (:8000), ingestion daemon (paused), dashboard (:3000), docs (:4000)
# Logs go to .devlogs/. Stop everything with scripts/stop.sh.
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
VENV="$ROOT/.venv/bin"
LOGS="$ROOT/.devlogs"
mkdir -p "$LOGS"

if lsof -ti tcp:8000 >/dev/null 2>&1; then
  echo "Port 8000 is already in use. Is the stack already running? Run scripts/stop.sh first."
  exit 1
fi

echo "Starting read API on :8000 ..."
"$VENV/uvicorn" app.main:app --port 8000 > "$LOGS/api.log" 2>&1 &
for _ in $(seq 1 20); do
  curl -sf http://localhost:8000/ >/dev/null 2>&1 && break
  sleep 0.5
done

# Bring the daemon up PAUSED so it makes zero requests to production until you
# click "Resume polling" in the dashboard. Protects prod's CPU between sessions.
# To start live instead, delete this curl line.
curl -s -X POST http://localhost:8000/api/polling/ \
  -H 'Content-Type: application/json' -d '{"enabled":false}' >/dev/null 2>&1

echo "Starting ingestion daemon (paused) ..."
"$VENV/python" -m app.pipeline > "$LOGS/daemon.log" 2>&1 &

echo "Starting dashboard on :3000 ..."
( cd frontend && npm run dev > "$LOGS/frontend.log" 2>&1 & )

echo "Starting docs on :4000 ..."
"$VENV/mkdocs" serve > "$LOGS/docs.log" 2>&1 &

sleep 5
echo
echo "Up:"
echo "  Dashboard  http://localhost:3000"
echo "  Read API   http://localhost:8000"
echo "  Docs       http://localhost:4000"
echo
echo "Daemon polling is PAUSED. Click 'Resume polling' in the dashboard for live data."
echo "Logs in $LOGS/   |   Stop with scripts/stop.sh"
