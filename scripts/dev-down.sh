#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/docker-compose.dev.yml" down
else
  docker compose -f "$ROOT_DIR/docker-compose.dev.yml" down
fi
