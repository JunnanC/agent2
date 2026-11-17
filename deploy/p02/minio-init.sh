#!/bin/sh
set -eu
mc alias set p02 http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing "p02/$MINIO_BUCKET"
mc version enable "p02/$MINIO_BUCKET"
mc admin user add p02 "$MINIO_APP_ACCESS_KEY" "$MINIO_APP_SECRET_KEY"
mc admin policy create p02 p02-app /policies/app-policy.json
mc admin policy attach p02 p02-app --user "$MINIO_APP_ACCESS_KEY"
mc ls "p02/$MINIO_BUCKET" >/dev/null
