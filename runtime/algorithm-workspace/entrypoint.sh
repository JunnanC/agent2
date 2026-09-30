#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

umask 077

CODE_SERVER_PID=''
ROUTER_PID=''

terminate() {
    trap - INT TERM EXIT
    if [ -n "$ROUTER_PID" ]; then kill -TERM "$ROUTER_PID" 2>/dev/null || true; fi
    if [ -n "$CODE_SERVER_PID" ]; then kill -TERM "$CODE_SERVER_PID" 2>/dev/null || true; fi
    if [ -n "$ROUTER_PID" ]; then wait "$ROUTER_PID" 2>/dev/null || true; fi
    if [ -n "$CODE_SERVER_PID" ]; then wait "$CODE_SERVER_PID" 2>/dev/null || true; fi
}

trap terminate INT TERM EXIT

mkdir -p \
    "$HOME" \
    "$XDG_CACHE_HOME" \
    "$XDG_CONFIG_HOME" \
    "$XDG_DATA_HOME" \
    "$XDG_RUNTIME_DIR" \
    /tmp/code-server/user-data/User
cp /opt/workspace-config/User/settings.json /tmp/code-server/user-data/User/settings.json

/opt/code-server/bin/code-server \
    --bind-addr 127.0.0.1:3000 \
    --auth none \
    --cert false \
    --disable-telemetry \
    --disable-update-check \
    --disable-workspace-trust \
    --disable-getting-started-override \
    --user-data-dir /tmp/code-server/user-data \
    --extensions-dir /opt/workspace-extensions \
    /workspace &
CODE_SERVER_PID=$!

/usr/local/bin/workspace-router &
ROUTER_PID=$!

while kill -0 "$CODE_SERVER_PID" 2>/dev/null && kill -0 "$ROUTER_PID" 2>/dev/null; do
    sleep 1 &
    wait $! || true
done

status=1
if ! kill -0 "$CODE_SERVER_PID" 2>/dev/null; then
    wait "$CODE_SERVER_PID" || status=$?
else
    wait "$ROUTER_PID" || status=$?
fi
exit "$status"
