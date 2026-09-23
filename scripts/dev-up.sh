#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEALTH_TIMEOUT_SECONDS=180

ensure_env() {
  local source_file="$1"
  local target_file="$2"
  if [[ ! -f "$target_file" ]]; then
    cp "$source_file" "$target_file"
  fi
}

ensure_env "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
ensure_env "$ROOT_DIR/frontend/.env.example" "$ROOT_DIR/frontend/.env"

set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env"
set +a

cd "$ROOT_DIR"
docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/docker-compose.dev.yml" up -d --build

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
until curl --fail --silent --max-time 2 "http://user.localhost:${ENTRY_PORT:-8080}/api/v2/health" >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Backend health check timed out after ${HEALTH_TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  sleep 2
done

echo "Local environment is ready: http://user.localhost:${ENTRY_PORT:-8080}"
