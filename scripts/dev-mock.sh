#!/usr/bin/env bash
set -euo pipefail

# Pantaray backend (Agents API) mock-mode launcher
# Usage:
#   bash scripts/dev-mock.sh               # defaults: PORT=8005 HOST=0.0.0.0 FRONTEND_PORT=3001
#   PORT=8010 bash scripts/dev-mock.sh     # override port via env
#   HOST=127.0.0.1 bash scripts/dev-mock.sh
#   ALLOWED_ORIGINS=http://localhost:3001 bash scripts/dev-mock.sh
#   RELOAD=true bash scripts/dev-mock.sh

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
AGENTS_DIR="$ROOT_DIR/agents"

PORT="${PORT:-8005}"
HOST="${HOST:-0.0.0.0}"
# Allow both localhost and 127.0.0.1 for dev server (unified to 3001)
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}}"
ALLOWED_HOSTS="${ALLOWED_HOSTS:-localhost,127.0.0.1}"
RELOAD="${RELOAD:-false}"
# Internal API settings (required for HTTP agents)
INTERNAL_API_MODE="${INTERNAL_API_MODE:-true}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-pantaray-internal-2025}"

# NOTE:
# - 本スクリプトは runtime_config loader に従い、
#   `agents/.env.local-runtime.dev` / `agents/.env.local-runtime` と明示 export 済み env のみを前提とする。
# - ローカル HTTP と Orchestration WS はランタイムが起動ごとに発行するローカル API
#   トークンで認証するため、Supabase の設定は要らない。

echo "[dev-mock] Starting Pantaray Agents API (mock)"
echo "[dev-mock]   HOST       : $HOST"
echo "[dev-mock]   PORT       : $PORT"
echo "[dev-mock]   ORIGINS    : $ALLOWED_ORIGINS"
echo "[dev-mock]   HOSTS      : $ALLOWED_HOSTS"
echo "[dev-mock]   RELOAD     : $RELOAD"
echo "[dev-mock]   INTERNAL_API_MODE: $INTERNAL_API_MODE"
echo "[dev-mock]   INTERNAL_API_KEY : (set)"

cd "$AGENTS_DIR"

# Ensure dependencies
# 備考: 以前 dev extra を個別に入れた環境でここで `--dev` のみを使うと、
# uv が「不要」とみなした dev extra（pytest など）を自動削除します。
# 一貫性のため dev extra を明示し、ロックを更新せず同期します。
uv sync --python 3.12 --extra dev --frozen

# Run in mock mode; runtime config stays in env, process launch config stays in CLI.
cmd=(uv run python -m pantaray_agents --mock --port "$PORT" --host "$HOST")
if [[ "$RELOAD" == "true" ]]; then
  cmd+=(--reload)
fi

FRONTEND_PORT="$FRONTEND_PORT" \
ALLOWED_ORIGINS="$ALLOWED_ORIGINS" \
ALLOWED_HOSTS="$ALLOWED_HOSTS" \
INTERNAL_API_MODE="$INTERNAL_API_MODE" \
INTERNAL_API_KEY="$INTERNAL_API_KEY" \
USE_MOCKS=true \
PYTHONPATH=src \
"${cmd[@]}"
