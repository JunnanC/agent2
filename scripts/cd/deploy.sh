#!/usr/bin/env bash
# Server prerequisites and first-cutover procedure: docs/开发指南/ACR-CD.md
set -Eeuo pipefail
umask 077
: "${ACR_REGISTRY:?}" "${ACR_NAMESPACE:?}" "${ACR_USERNAME:?}" "${ACR_PASSWORD:?}" "${RELEASE_SHA:?}"
[[ "$RELEASE_SHA" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ "$ACR_REGISTRY" =~ ^[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || exit 2
[[ "$ACR_NAMESPACE" =~ ^[a-z0-9_-]+$ ]] || exit 2
[[ "$(git rev-parse HEAD)" == "$RELEASE_SHA" ]] || exit 2
root=/opt/agent2-cd
config=/etc/agent2-cd
# This host's old volumes have underscores; defaults in new Compose use hyphens.
# Require a reviewed server override rather than silently creating empty databases.
test -r "$config/.env"
test -r "$config/compose.override.yml"
test -s "$config/secrets/workspace_upstream_token"
test -d "$root/releases"
exec 9>"$root/deploy.lock"
flock -w 30 9
release=$(mktemp -d "$root/releases/${RELEASE_SHA}.XXXXXX")
git archive HEAD | tar -x -C "$release"
cp "$config/.env" "$release/.env"
cp "$config/compose.override.yml" "$release/server.yml"
ln -s "$config/secrets" "$release/secrets"
export COMPOSE_PROJECT_NAME=edu-platform
export GIT_REVISION="$RELEASE_SHA"
export LOCAL_RUNTIME_IMAGE="$ACR_REGISTRY/$ACR_NAMESPACE/agent2-workspace:$RELEASE_SHA"
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
printf '%s' "$ACR_PASSWORD" | docker login "$ACR_REGISTRY" --username "$ACR_USERNAME" --password-stdin
unset ACR_PASSWORD
python3 - "$release/images.json" <<'PY'
import json, os, sys
prefix = os.environ['ACR_REGISTRY'] + '/' + os.environ['ACR_NAMESPACE'] + '/agent2-'
sha = os.environ['RELEASE_SHA']
services = {name: {'image': prefix + 'backend:' + sha} for name in (
    'migrate', 'core-check', 'django', 'celery', 'runtime-worker',
    'workspace-storage-worker', 'workspace-gateway', 'celery-beat', 'log-ingest')}
services['nginx'] = {'image': prefix + 'web:' + sha}
services['runtime-reference'] = {'image': prefix + 'reference:' + sha}
services['runtime-algorithm-workspace'] = {'image': prefix + 'workspace:' + sha}
with open(sys.argv[1], 'w') as f:
    json.dump({'services': services}, f)
PY
# Keep the runtime network and all other release variables available on recovery.
printf '\nGIT_REVISION=%s\nLOCAL_RUNTIME_IMAGE=%s\n' "$GIT_REVISION" "$LOCAL_RUNTIME_IMAGE" >> "$release/.env"
compose=(docker compose --project-directory "$release" --env-file "$release/.env" -p edu-platform
  -f "$release/docker-compose.dev.yml" -f "$release/server.yml" -f "$release/images.json")
"${compose[@]}" config --format json > "$release/resolved.json"
python3 - "$release/resolved.json" <<'PY'
import json, subprocess, sys
c = json.load(open(sys.argv[1]))
for key in ('mysql-data', 'redis-data', 'mongo-data', 'mongo-keyfile', 'minio-data', 'clamav-data', 'fluent-bit-buffer'):
    v = c['volumes'][key]
    expected = 'edu-platform_' + key
    if not v.get('external') or v.get('name') != expected:
        raise SystemExit('Existing volume must be explicitly mapped: ' + expected)
    subprocess.run(['docker', 'volume', 'inspect', expected], check=True, stdout=subprocess.DEVNULL)
PY
"${compose[@]}" --profile runtime pull --policy always
# A failed backup stops deployment before migrations or service changes.
mkdir -p "$root/backups"
backup="$root/backups/mysql-${RELEASE_SHA}-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
mysql_id=$(docker ps -q --filter label=com.docker.compose.project=edu-platform --filter label=com.docker.compose.service=mysql)
test -n "$mysql_id"
docker exec "$mysql_id" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces --databases "$MYSQL_DATABASE"' | gzip > "$backup"
gzip -t "$backup"
# Compose runs the migrate/mysql-grants dependency chain. No volume deletion/prune.
# Database migrations cannot be safely undone by reverting application images.
"${compose[@]}" --profile runtime up -d --no-build --wait --wait-timeout 600
"${compose[@]}" restart kong nginx
curl --fail --silent --show-error --retry 12 --retry-connrefused --retry-delay 5 http://127.0.0.1/api/v2/health >/dev/null
for portal in student teacher admin; do
  curl --fail --silent --show-error -H "Cookie: portal=$portal" http://127.0.0.1/ >/dev/null
done
ln -s "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf 'Deployed %s\nBackup: %s\n' "$RELEASE_SHA" "$backup"
