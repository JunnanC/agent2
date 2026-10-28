#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

umask 077

TTYD_PID=''
CODE_SERVER_PID=''
ROUTER_PID=''

terminate() {
    trap - INT TERM EXIT
    for pid in "$TTYD_PID" "$ROUTER_PID" "$CODE_SERVER_PID"; do
        if [ -n "$pid" ]; then kill -TERM "$pid" 2>/dev/null || true; fi
    done
    for pid in "$TTYD_PID" "$ROUTER_PID" "$CODE_SERVER_PID"; do
        if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || true; fi
    done
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

# 真实终端:ttyd 以 -W 连接到真实 shell,router 以 /terminal/ 前缀分发到此端口。
# 通过线路上游(X-Workspace-Upstream-Token)在 router 鉴权;详细的终端参数保持:
# interface=127.0.0.1(仅环路)、base-path=/terminal(网关保留能力前缀)、port=7681。
if [ -x /usr/local/bin/ttyd ]; then
    /usr/local/bin/ttyd \
        --interface 127.0.0.1 \
        --port 7681 \
        --base-path /terminal \
        --writable \
        /bin/bash &
    TTYD_PID=$!
fi

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
