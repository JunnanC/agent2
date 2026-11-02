#!/usr/bin/env bash
# 构建并启动本地 Compose 服务，检查学生门户健康接口。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HEALTH_TIMEOUT_SECONDS=180

ensure_env() {
  local source_file="$1"
  local target_file="$2"
  if [[ ! -f "$target_file" ]]; then
    cp "$source_file" "$target_file"
  fi
}

ensure_env "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"

cd "$ROOT_DIR"
docker compose --profile runtime --env-file "$ROOT_DIR/.env" up -d --build
docker compose --env-file "$ROOT_DIR/.env" restart kong nginx
entry_address="$(docker compose --env-file "$ROOT_DIR/.env" port nginx 8080 | head -n 1)"
entry_port="${entry_address##*:}"

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
until curl --fail --silent --max-time 2 "http://student.localhost:${entry_port}/api/v2/health" >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Backend health check timed out after ${HEALTH_TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  sleep 2
done

echo "Local environment is ready: http://student.localhost:${entry_port}"
