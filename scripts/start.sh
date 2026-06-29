#!/usr/bin/env bash
# Bring up the whole LM Dashboard stack in the background. Each process logs to
# .devlogs/. Tear it all back down (tunnel included) with scripts/stop.sh.
#
#   scripts/start.sh           local dev: Vite dev server on :3000, hot reload
#   scripts/start.sh --prod    local: production build served on :3000
#   scripts/start.sh --remote  GATED + exposed via ngrok. The API itself serves the
#                              UI (no :3000), and the prod login is REQUIRED, so
#                              there is no way to expose an ungated dashboard.
#
# --remote sets NGROK_URL to a default; override it:  NGROK_URL=https://x scripts/start.sh --remote
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
VENV="$ROOT/.venv/bin"
LOGS="$ROOT/.devlogs"
mkdir -p "$LOGS"

FRONTEND_MODE="dev"
REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --prod|prod)     FRONTEND_MODE="prod" ;;
    --remote|remote) REMOTE=1 ;;
  esac
done

if lsof -ti tcp:8000 >/dev/null 2>&1; then
  echo "Port 8000 is already in use. Is the stack already running? Run scripts/stop.sh first."
  exit 1
fi

# --remote: turn on the prod-credential gate and serve the UI from the API itself
# (single origin). The gate lives in this launch environment only, so local runs
# and the test suite stay open.
if [ "$REMOTE" = "1" ]; then
  command -v ngrok >/dev/null || { echo "ngrok not installed (brew install ngrok)"; exit 1; }
  export DASHBOARD_AUTH=prod
  echo "Building UI for single-origin remote serving ..."
  ( cd frontend && VITE_API_URL='' npm run build > "$LOGS/frontend-build.log" 2>&1 )
fi

echo "Starting read API on :8000 ..."
"$VENV/uvicorn" app.main:app --port 8000 > "$LOGS/api.log" 2>&1 &
# Wait for it to answer. Use -s (not -f): a gated API replies 401, which still
# means "up". /healthz is the liveness route.
for _ in $(seq 1 20); do
  curl -s -o /dev/null http://127.0.0.1:8000/healthz && break
  sleep 0.5
done

# Start the daemon PAUSED so it makes no requests to production until you click
# "Resume polling" in the dashboard. Set the flag straight in the DB (works even
# when the API is gated, where an unauthenticated POST would be rejected).
"$VENV/python" -c "from app import db; db.set_meta('polling_enabled','0')" 2>/dev/null

echo "Starting ingestion daemon (paused) ..."
# Remote/served sessions arm the dead-man's switch: prod polling auto-pauses
# whenever no dashboard is open (the read API stamps viewer_last_seen on each
# poll, and the frontend stops polling when its tab is hidden). Local sessions
# leave it off so a manual run polls normally.
[ "$REMOTE" = "1" ] && export PIPELINE_REQUIRE_VIEWER=1
"$VENV/python" -m app.pipeline > "$LOGS/daemon.log" 2>&1 &

# Local dashboard on :3000 only when NOT remote (remote serves the UI from :8000).
if [ "$REMOTE" != "1" ]; then
  if [ "$FRONTEND_MODE" = "prod" ]; then
    echo "Building + serving dashboard on :3000 (production) ..."
    ( cd frontend \
        && npm run build > "$LOGS/frontend-build.log" 2>&1 \
        && npm run preview -- --port 3000 --strictPort > "$LOGS/frontend.log" 2>&1 & )
  else
    echo "Starting dashboard on :3000 (dev) ..."
    ( cd frontend && npm run dev > "$LOGS/frontend.log" 2>&1 & )
  fi
fi

echo "Starting docs on :4000 ..."
"$VENV/mkdocs" serve > "$LOGS/docs.log" 2>&1 &

# --remote: open the tunnel, but only after confirming the API is gated (a no-login
# request must get 401). Belt-and-suspenders, even though --remote sets the gate.
NGROK_URL="${NGROK_URL:-https://unretired-generic-backache.ngrok-free.dev}"
if [ "$REMOTE" = "1" ]; then
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ || true)
  if [ "$code" = "401" ]; then
    nohup ngrok http --url="${NGROK_URL#https://}" 8000 --log=stdout > "$LOGS/ngrok.log" 2>&1 &
    echo $! > "$ROOT/.ngrok.pid"
    echo "Tunnel open -> $NGROK_URL"
  else
    echo "WARNING: API answered '$code' to a no-login request (NOT gated) -- tunnel NOT opened."
  fi
fi

sleep 5
echo
echo "Up:"
if [ "$REMOTE" = "1" ]; then
  echo "  Dashboard (remote)  $NGROK_URL   (log in with the prod credentials)"
  echo "  Dashboard (local)   http://localhost:8000   (also behind the login)"
else
  echo "  Dashboard  http://localhost:3000"
fi
echo "  Read API   http://localhost:8000"
echo "  Docs       http://localhost:4000"
echo
echo "Dashboard mode: $([ "$REMOTE" = 1 ] && echo remote || echo "$FRONTEND_MODE")"
echo "Daemon polling is PAUSED. Click 'Resume polling' in the dashboard for live data."
echo "Logs in $LOGS/   |   Stop with scripts/stop.sh"
