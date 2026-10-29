#!/bin/sh
set -eu

: "${STUDENT_HOST:?STUDENT_HOST is required}"
: "${TEACHER_HOST:?TEACHER_HOST is required}"
: "${ADMIN_HOST:?ADMIN_HOST is required}"
: "${API_HOST:?API_HOST is required}"

envsubst '${STUDENT_HOST} ${TEACHER_HOST} ${ADMIN_HOST} ${API_HOST}' \
  < /etc/nginx/nginx.conf.template \
  > /etc/nginx/nginx.conf

exec /docker-entrypoint.sh "$@"
