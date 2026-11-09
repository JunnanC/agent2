#!/usr/bin/env bash
# Server prerequisites and first-cutover procedure: docs/开发指南/ACR-CD.md
set -Eeuo pipefail
umask 077
: "${ACR_REGISTRY:?}" "${ACR_NAMESPACE:?}" "${RELEASE_SHA:?}"
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
# Containers read this bind mount with a different UID. Only source is public
# within the mount; .env and resolved.json retain mode 0600. Parent dirs are 0700.
chmod 0755 "$release"
git archive HEAD | (umask 022; tar -x -C "$release")
cp "$config/.env" "$release/.env"
cp "$config/compose.override.yml" "$release/server.yml"
# An absolute host symlink is broken inside the /workspace bind mount.
mkdir -m 0755 "$release/secrets"
install -m 0444 "$config/secrets/workspace_upstream_token" "$release/secrets/workspace_upstream_token"
export COMPOSE_PROJECT_NAME=edu-platform
export GIT_REVISION="$RELEASE_SHA"
export LOCAL_RUNTIME_IMAGE="$ACR_REGISTRY/$ACR_NAMESPACE/agent2-workspace:$RELEASE_SHA"
export DOCKER_SOCKET_GID
DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
export CELERY_CONCURRENCY=1 RUNTIME_WORKER_CONCURRENCY=1
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
for name in ('mysql', 'redis', 'mongodb', 'minio', 'fluent-bit', 'kong', 'nginx',
             'mongo-keyfile', 'mongo-init', 'mysql-users', 'mysql-grants', 'minio-init',
             'django', 'celery', 'migrate', 'runtime-worker', 'workspace-storage-worker',
             'workspace-gateway', 'log-ingest', 'runtime-reference'):
    services.setdefault(name, {})['container_name'] = 'edu-platform-' + name + '-1'
with open(sys.argv[1], 'w') as f:
    json.dump({'services': services}, f)
PY
# Keep the runtime network and all other release variables available on recovery.
printf '\nGIT_REVISION=%s\nLOCAL_RUNTIME_IMAGE=%s\n' "$GIT_REVISION" "$LOCAL_RUNTIME_IMAGE" >> "$release/.env"
printf 'DOCKER_SOCKET_GID=%s\nCELERY_CONCURRENCY=1\nRUNTIME_WORKER_CONCURRENCY=1\n' "$DOCKER_SOCKET_GID" >> "$release/.env"
compose=(docker compose --project-directory "$release" --env-file "$release/.env" -p edu-platform
  -f "$release/docker-compose.dev.yml" -f "$release/server.yml" -f "$release/images.json")
"${compose[@]}" --profile runtime config --format json > "$release/resolved.json"
python3 "$release/scripts/cd/check-portal-origins.py" "$release/.env" "$release/resolved.json"
python3 - "$release/resolved.json" <<'PY'
import json, subprocess, sys
c = json.load(open(sys.argv[1]))
for key in ('mysql-data', 'redis-data', 'mongo-data', 'mongo-keyfile', 'minio-data', 'clamav-data', 'fluent-bit-buffer'):
    v = c['volumes'][key]
    expected = 'edu-platform_' + key
    if not v.get('external') or v.get('name') != expected:
        raise SystemExit('Existing volume must be explicitly mapped: ' + expected)
    subprocess.run(['docker', 'volume', 'inspect', expected], check=True, stdout=subprocess.DEVNULL)
for key, net in c['networks'].items():
    expected = 'edu-platform_' + key
    if net.get('name') != expected:
        raise SystemExit('Existing network must be explicitly mapped: ' + expected)
    subprocess.run(['docker', 'network', 'inspect', expected], check=True, stdout=subprocess.DEVNULL)
for name in ('mysql', 'redis', 'mongodb', 'minio', 'fluent-bit'):
    ids = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=edu-platform',
                                   '--filter', 'label=com.docker.compose.service=' + name], text=True).split()
    if len(ids) != 1:
        raise SystemExit('Infrastructure must already be running: ' + name)
    state = json.loads(subprocess.check_output(['docker', 'inspect', ids[0]], text=True))[0]['State']
    if state.get('Health', {}).get('Status', 'healthy') != 'healthy':
        raise SystemExit('Infrastructure is unhealthy: ' + name)
PY
if [[ "${DEPLOY_PREFLIGHT_ONLY:-false}" == true ]]; then
  printf 'Preflight passed. No images pulled, migrations run, or services changed.\nRelease: %s\n' "$release"
  exit 0
fi
: "${ACR_USERNAME:?}" "${ACR_PASSWORD:?}"
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
printf '%s' "$ACR_PASSWORD" | docker login "$ACR_REGISTRY" --username "$ACR_USERNAME" --password-stdin
unset ACR_PASSWORD
# Fetch all four images, including the workspace image used by dynamic labs.
# Explicit service names do not start the optional monitoring/scanner services.
"${compose[@]}" pull --policy always django nginx runtime-reference runtime-algorithm-workspace
# A failed backup stops deployment before migrations or service changes.
mkdir -p "$root/backups"
backup="$root/backups/mysql-${RELEASE_SHA}-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
mysql_id=$(docker ps -q --filter label=com.docker.compose.project=edu-platform --filter label=com.docker.compose.service=mysql)
test -n "$mysql_id"
docker exec "$mysql_id" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces --databases "$MYSQL_DATABASE"' | gzip > "$backup"
gzip -t "$backup"
# The existing database, storage, Redis and logging containers stay running.
# Stop application writers before schema changes. Failures after this point may
# need manual recovery; reverting an image cannot undo database migrations.
managed=(django celery runtime-worker workspace-storage-worker workspace-gateway log-ingest)
"${compose[@]}" --profile runtime stop "${managed[@]}"
for task in mysql-users migrate mysql-grants; do
  "${compose[@]}" run --rm --no-deps "$task"
done
# Do not start ClamAV, monitoring, beat or an idle algorithm workspace on this
# 4 GiB host. Those require a separate capacity and lifecycle decision.
"${compose[@]}" --profile runtime up -d --no-deps --no-build --wait --wait-timeout 600 \
  "${managed[@]}" runtime-reference kong nginx
"${compose[@]}" restart kong nginx
curl --fail --silent --show-error --retry 12 --retry-connrefused --retry-delay 5 http://127.0.0.1/api/v2/health >/dev/null
for portal in student teacher admin; do
  curl --fail --silent --show-error -H "Cookie: portal=$portal" http://127.0.0.1/ >/dev/null
done
ln -s "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf 'Deployed %s\nBackup: %s\n' "$RELEASE_SHA" "$backup"
