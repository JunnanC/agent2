#!/usr/bin/env bash
# 停止并移除本地 Compose 服务，保留持久数据卷。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  docker compose --profile runtime --env-file "$ROOT_DIR/.env" down
else
  docker compose --profile runtime -f "$ROOT_DIR/docker-compose.dev.yml" down
fi
