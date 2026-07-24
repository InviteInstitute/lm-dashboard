#!/usr/bin/env bash
# Deploy the latest to this prod server via docker compose: pull, rebuild the
# images, and roll the stack (db + api + daemon), then verify /healthz. The schema
# is created by the API on startup (db.init_db), so there is no separate migration
# step for new tables. Refuses to run over uncommitted changes to tracked files --
# commit, stash, or discard them first so a pull never silently clobbers edits.
#
# Prereqs on this host: Docker + the compose v2 plugin, a `.env` with
# POSTGRES_PASSWORD, and `.env.mirror` with the app secrets (see .env.example).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Deploying LM Dashboard (docker compose) ..."

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

echo "Building + rolling the stack ..."
docker compose -f compose.yml up -d --build

echo "Waiting for the API to come back up ..."
for _ in $(seq 1 30); do
  curl -s -o /dev/null http://127.0.0.1:8000/healthz && break
  sleep 1
done

code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/healthz)
if [ "$code" = "200" ]; then
  echo "Deploy OK -- /healthz = 200"
else
  echo "WARNING: /healthz returned $code -- check: docker compose -f compose.yml logs api"
  exit 1
fi

docker compose -f compose.yml ps
echo "Polling is per-board and gated by the dead-man switch (a board is only polled while its dashboard is open)."
