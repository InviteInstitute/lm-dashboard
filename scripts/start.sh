#!/usr/bin/env bash
# Bring up the whole LM Dashboard stack in the background:
#   read API (:8000), ingestion daemon (started PAUSED), dashboard (:3000), docs (:4000).
# Each process logs to .devlogs/. Tear it all back down with scripts/stop.sh.
#
#   ./scripts/start.sh           dashboard in DEV mode (Vite dev server, hot reload)
#   ./scripts/start.sh --prod    dashboard as a PRODUCTION build (built + served)
#
# Use --prod for a real data-collection session: it's lighter and effects run
# once, so a stray file save can't hot-reload and reset your open modal/notes.
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
VENV="$ROOT/.venv/bin"
LOGS="$ROOT/.devlogs"
mkdir -p "$LOGS"

FRONTEND_MODE="dev"
if [ "$1" = "--prod" ] || [ "$1" = "prod" ]; then
  FRONTEND_MODE="prod"
fi

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

# Start the daemon PAUSED: it makes no requests to production until you click
# "Resume polling" in the dashboard, which keeps load off prod between sessions.
# Want it live from the start? Just delete this curl call.
curl -s -X POST http://localhost:8000/api/polling/ \
  -H 'Content-Type: application/json' -d '{"enabled":false}' >/dev/null 2>&1

echo "Starting ingestion daemon (paused) ..."
"$VENV/python" -m app.pipeline > "$LOGS/daemon.log" 2>&1 &

if [ "$FRONTEND_MODE" = "prod" ]; then
  echo "Building + serving dashboard on :3000 (production) ..."
  # Build first, then serve the static bundle with Vite's preview server. The
  # build can take a few seconds, so the dashboard comes up shortly after the
  # URLs print below.
  ( cd frontend \
      && npm run build > "$LOGS/frontend-build.log" 2>&1 \
      && npm run preview -- --port 3000 --strictPort > "$LOGS/frontend.log" 2>&1 & )
else
  echo "Starting dashboard on :3000 (dev) ..."
  ( cd frontend && npm run dev > "$LOGS/frontend.log" 2>&1 & )
fi

echo "Starting docs on :4000 ..."
"$VENV/mkdocs" serve > "$LOGS/docs.log" 2>&1 &

sleep 5
echo
echo "Up:"
echo "  Dashboard  http://localhost:3000"
echo "  Read API   http://localhost:8000"
echo "  Docs       http://localhost:4000"
echo
echo "Dashboard mode: $FRONTEND_MODE   (use --prod for data collection)"
echo "Daemon polling is PAUSED. Click 'Resume polling' in the dashboard for live data."
echo "Logs in $LOGS/   |   Stop with scripts/stop.sh"
