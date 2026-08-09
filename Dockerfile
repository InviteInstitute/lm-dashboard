# syntax=docker/dockerfile:1
# One image for both the API and the daemon (they differ only by command). The
# React SPA is built in a first stage and copied into frontend/dist, which the
# API serves at / in production.

# ---- Stage 1: build the React SPA ----
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
# frontend/.env.production pins VITE_API_URL='' -> a same-origin build.
RUN npm run build          # -> /web/dist

# ---- Stage 2: Python runtime (shared by the api + daemon services) ----
FROM python:3.12-slim AS app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml requirements.txt ./
COPY app/ ./app/
COPY scripts/ ./scripts/
# editable install; pyproject.toml is the single source of truth for deps.
RUN pip install -e .
COPY --from=web /web/dist ./frontend/dist
EXPOSE 8000
# Default is the API; the daemon service overrides this command in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
