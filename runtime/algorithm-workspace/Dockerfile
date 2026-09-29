# syntax=m.daocloud.io/docker.io/docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

ARG GO_BUILDER_IMAGE=m.daocloud.io/docker.io/library/golang:1.25.1-alpine3.22@sha256:546671046d6f9f786c24b83111ba1801b736ee4b01b23db33e4f3eb41d4f8883
ARG PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.14.0-slim-bookworm@sha256:9bbb8720ae0a24a6ca8dd678bfdf57818fe70caf54c52a53ec01d8db43405056

FROM ${GO_BUILDER_IMAGE} AS router-builder
WORKDIR /src
COPY router/go.mod router/main.go router/main_test.go ./
RUN go test ./... \
    && CGO_ENABLED=0 GOOS=linux go build \
      -trimpath -ldflags="-s -w -buildid=" \
      -o /out/workspace-router .

FROM ${PYTHON_BASE_IMAGE} AS code-server-downloader
ARG CODE_SERVER_VERSION=4.104.2
ARG CODE_SERVER_SHA256=bc650b57fd8d0bcee952c97308dd43ae37ad8dc11b83a713d8eca8ce823fefd9
ADD --checksum=sha256:${CODE_SERVER_SHA256} \
    https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-amd64.tar.gz \
    /tmp/code-server.tar.gz
RUN mkdir -p /opt/code-server \
    && tar -xzf /tmp/code-server.tar.gz --strip-components=1 -C /opt/code-server \
    && /opt/code-server/bin/code-server --version | grep -F "${CODE_SERVER_VERSION}"

FROM ${PYTHON_BASE_IMAGE}
ARG CODE_SERVER_VERSION=4.104.2

LABEL org.opencontainers.image.title="Education Algorithm Workspace" \
      org.opencontainers.image.description="Isolated Python workspace with code-server and an authenticated internal router" \
      org.opencontainers.image.version="p16-b" \
      org.opencontainers.image.source="https://github.com/JunnanC/agent2" \
      edu.platform.code-server.version="${CODE_SERVER_VERSION}" \
      edu.platform.python.version="3.14.0" \
      edu.platform.workspace.capabilities="webide,snapshot,checkpoint" \
      edu.platform.workspace.contract="p16-b"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/workspace-home \
    XDG_CACHE_HOME=/tmp/xdg/cache \
    XDG_CONFIG_HOME=/tmp/xdg/config \
    XDG_DATA_HOME=/tmp/xdg/data \
    XDG_RUNTIME_DIR=/tmp/xdg/runtime \
    EXTENSIONS_GALLERY='{"serviceUrl":""}' \
    WORKSPACE_UPSTREAM_TOKEN_FILE=/run/secrets/workspace_upstream_token \
    WORKSPACE_CODE_SERVER_URL=http://127.0.0.1:3000 \
    WORKSPACE_ROUTER_ADDR=0.0.0.0:8080

RUN groupadd --gid 10001 workspace \
    && useradd --uid 10001 --gid workspace --home-dir /tmp/workspace-home --shell /bin/sh workspace \
    && mkdir -p /opt/workspace-config/User /opt/workspace-extensions /workspace \
    && printf '[]\n' > /opt/workspace-extensions/extensions.json \
    && chown workspace:workspace /workspace \
    && chmod 0555 /opt/workspace-extensions \
    && chmod 0444 /opt/workspace-extensions/extensions.json

COPY --from=code-server-downloader /opt/code-server /opt/code-server
COPY --from=router-builder /out/workspace-router /usr/local/bin/workspace-router
COPY entrypoint.sh /usr/local/bin/workspace-entrypoint
COPY settings.json /opt/workspace-config/User/settings.json
RUN chmod 0555 /usr/local/bin/workspace-router /usr/local/bin/workspace-entrypoint \
    && chmod 0444 /opt/workspace-config/User/settings.json

USER 10001:10001
WORKDIR /workspace
EXPOSE 8080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
    CMD ["/usr/local/bin/workspace-router", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/workspace-entrypoint"]
