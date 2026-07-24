#!/usr/bin/env bash
# Deploy the latest main to this prod server: pull, install/build only what
# changed, restart the systemd-managed services, then verify /healthz.
# Refuses to run over uncommitted changes to tracked files -- commit, stash,
# or discard them first so a pull never silently clobbers server-side edits.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
VENV="$ROOT/.venv/bin"

echo "Deploying LM Dashboard ..."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Working tree has uncommitted changes to tracked files -- aborting:"
  git status --short
  exit 1
fi

BEFORE=$(git rev-parse HEAD)
git pull --ff-only
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
  echo "Already up to date ($AFTER)."
else
  echo "Updated $BEFORE -> $AFTER"
fi

CHANGED=$(git diff --name-only "$BEFORE" "$AFTER")

if echo "$CHANGED" | grep -q "^requirements.txt$"; then
  echo "requirements.txt changed -- installing ..."
  "$VENV/pip" install -r requirements.txt
fi

if echo "$CHANGED" | grep -qE "^frontend/(package(-lock)?\.json|src/|index\.html|vite\.config)"; then
  echo "Frontend changed -- installing + building ..."
  ( cd frontend && npm ci && npm run build )
fi

echo "Restarting services ..."
sudo systemctl restart lm-dashboard-api.service
sudo systemctl restart lm-dashboard-daemon.service

echo "Waiting for the API to come back up ..."
for _ in $(seq 1 20); do
  curl -s -o /dev/null http://127.0.0.1:8000/healthz && break
  sleep 0.5
done

code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/healthz)
if [ "$code" = "200" ]; then
  echo "Deploy OK -- /healthz = 200"
else
  echo "WARNING: /healthz returned $code -- check: sudo journalctl -u lm-dashboard-api -n 50"
  exit 1
fi

if sudo systemctl is-active --quiet lm-dashboard-daemon.service; then
  echo "Daemon: active (polling starts PAUSED -- resume it from the dashboard if needed)"
else
  echo "WARNING: daemon not active -- check: sudo journalctl -u lm-dashboard-daemon -n 50"
fi
