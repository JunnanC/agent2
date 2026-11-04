#!/bin/sh
set -eu
export GOCACHE="${GOCACHE:-/workspace/.cache/go-build}"
export GOTMPDIR="${GOTMPDIR:-/workspace/.cache/go-tmp}"
mkdir -p "$GOCACHE" "$GOTMPDIR"
exec /usr/local/go/bin/go "$@"
