<#
.SYNOPSIS
验证 MySQL 追加权限、Redis 数据丢失恢复、并发幂等和 Outbox 转发。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [string]$ProjectName = 'experimental-platform-core-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') {
    throw 'ProjectName must be a narrow Docker Compose project identifier.'
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants
    if ($LASTEXITCODE -ne 0) { throw 'Shared infrastructure data services failed to start.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
mysql --host=127.0.0.1 --user=root "$MYSQL_DATABASE" --execute="
INSERT INTO core_outbox_event
  (id, event_type, aggregate_type, aggregate_ref, payload, trace_id, created_at)
VALUES
  ('00000000000000000000000000000001', 'verify.permission', 'verify', 'opaque-1', JSON_OBJECT(), REPEAT('a', 32), UTC_TIMESTAMP(6));"
'@
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the AppendOnly permission probe.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --execute="
UPDATE core_outbox_event SET event_type='forbidden' WHERE id='00000000000000000000000000000001';"
'@
    if ($LASTEXITCODE -eq 0) { throw 'Application DB account unexpectedly updated an AppendOnly row.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
mysql --host=127.0.0.1 --user=root "$MYSQL_DATABASE" --execute="
DELETE FROM core_outbox_event WHERE id='00000000000000000000000000000001';"
'@
    if ($LASTEXITCODE -ne 0) { throw 'Could not clean the AppendOnly permission probe.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --execute="
INSERT INTO core_failure_record
  (failure_type, subject_type, subject_ref, error_code, message_masked, detail_masked, retryable, trace_id, created_at)
VALUES
  ('VERIFY', 'verify', 'opaque-redis', 'VERIFY_ONLY', '', JSON_OBJECT(), 0, REPEAT('b', 32), UTC_TIMESTAMP(6));"
'@
    if ($LASTEXITCODE -ne 0) { throw 'Restricted application DB account could not append a core fact.' }

    & docker @compose exec -T redis redis-cli FLUSHDB
    if ($LASTEXITCODE -ne 0) { throw 'Redis recovery probe failed.' }
    & docker @compose exec -T redis redis-cli PING
    if ($LASTEXITCODE -ne 0) { throw 'Redis did not recover after the probe.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
count="$(mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT COUNT(*) FROM core_failure_record WHERE subject_ref='opaque-redis';")"
test "$count" = "1"
'@
    if ($LASTEXITCODE -ne 0) { throw 'MySQL facts did not survive the Redis loss probe.' }

    & docker @compose --profile tools run --rm --no-deps core-check python manage.py verify_core_concurrency
    if ($LASTEXITCODE -ne 0) { throw 'MySQL CAS or idempotency concurrency verification failed.' }

    & docker @compose --profile tools run --rm --no-deps core-check python manage.py shell -c @'
from apps.core.outbox import append_outbox_event
append_outbox_event(event_type="verify.relay", aggregate_type="verify", aggregate_ref="opaque-relay", payload={"safe": "visible"}, trace_id="c" * 32)
'@
    if ($LASTEXITCODE -ne 0) { throw 'Could not append the relay verification event.' }
    & docker @compose --profile tools run --rm --no-deps core-check python manage.py relay_outbox
    if ($LASTEXITCODE -ne 0) { throw 'Real Redis Outbox relay failed.' }
    & docker @compose exec -T redis sh -ec 'test "$(redis-cli XLEN edu:events:v2)" -ge 1'
    if ($LASTEXITCODE -ne 0) { throw 'Redis Stream did not receive the Outbox event.' }

    Write-Output 'Shared infrastructure MySQL permissions and Redis recovery verification passed.'
} finally {
    if (-not $KeepEnvironment) {
        & docker @compose down --volumes --remove-orphans
    }
}
