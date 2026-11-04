ARG GO_BUILDER_IMAGE=public.ecr.aws/docker/library/golang:1.25.1-alpine3.22@sha256:546671046d6f9f786c24b83111ba1801b736ee4b01b23db33e4f3eb41d4f8883
ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.14.0-slim-bookworm@sha256:9bbb8720ae0a24a6ca8dd678bfdf57818fe70caf54c52a53ec01d8db43405056

# ttyd is statically linked and its digest is pinned against the official
# SHA256SUMS asset of the 1.7.7 release (release-asset cross-verified).
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55

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

FROM ${GO_BUILDER_IMAGE} AS debug-tools-builder
ENV GOMAXPROCS=2 GOFLAGS=-p=2 GOBIN=/out CGO_ENABLED=0
RUN go install github.com/go-delve/delve/cmd/dlv@v1.25.1 \
    && go install golang.org/x/tools/gopls@v0.20.0

FROM scratch AS debug-vsix
ADD --checksum=sha256:a7f93951c5e575728529b3db9d6eb4dc9b2eb79de7d356b378385630349de27c \
    https://open-vsx.org/api/webfreak/debug/0.27.0/file/webfreak.debug-0.27.0.vsix /webfreak.debug.vsix
ADD --checksum=sha256:1da755a39e10222f79d3523bd991ce58ef6c31b1424daab704a3c64b15325799 \
    https://open-vsx.org/api/redhat/java/linux-x64/1.37.0/file/redhat.java-1.37.0@linux-x64.vsix /redhat.java.vsix
ADD --checksum=sha256:1dc2a6c87abc9a4309c65bffb44952ba1e95b70a30d16058a38f37b142ca64b2 \
    https://open-vsx.org/api/vscjava/vscode-java-debug/0.58.2/file/vscjava.vscode-java-debug-0.58.2.vsix /vscjava.vscode-java-debug.vsix
ADD --checksum=sha256:7b43b91174adc47c3bb0aa331faab32d2333cb4d12fba43ba7d2ad3fe35b07a6 \
    https://open-vsx.org/api/golang/Go/0.50.0/file/golang.Go-0.50.0.vsix /golang.go.vsix
ADD --checksum=sha256:d561d57f5820c0bdbc2b822f417e524afba256c60b28a9a1670f7923b1bddabc \
    https://open-vsx.org/api/ms-python/python/2025.14.0/file/ms-python.python-2025.14.0.vsix /ms-python.python.vsix
ADD --checksum=sha256:fd3e00e4b45acf3b86508ef491f7dafb03e3174f8cae24e3c2f82f19c30a30dd \
    https://open-vsx.org/api/ms-python/debugpy/linux-x64/2025.14.1/file/ms-python.debugpy-2025.14.1@linux-x64.vsix /ms-python.debugpy.vsix

FROM code-server-downloader AS debug-extensions-builder
COPY --from=debug-vsix / /opt/debug-vsix/
COPY debug-extensions.lock.json /opt/debug-extensions.lock.json
COPY install-debug-extensions.py /opt/install-debug-extensions.py
RUN python /opt/install-debug-extensions.py

FROM ${PYTHON_BASE_IMAGE} AS ttyd-downloader
ARG TTYD_VERSION
ARG TTYD_SHA256
ADD --checksum=sha256:${TTYD_SHA256} \
    https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64 \
    /usr/local/bin/ttyd
RUN chmod 0755 /usr/local/bin/ttyd && echo "${TTYD_VERSION}" | grep -F "$(ttyd --version | awk '{print $3}' | cut -d- -f1)"

FROM ${PYTHON_BASE_IMAGE}
ARG CODE_SERVER_VERSION=4.104.2
ARG TTYD_VERSION=1.7.7

LABEL org.opencontainers.image.title="Education Algorithm Workspace" \
      org.opencontainers.image.description="Isolated multi-language workspace with code-server and an authenticated internal router" \
      org.opencontainers.image.version="p16-c" \
      org.opencontainers.image.source="https://github.com/JunnanC/agent2" \
      edu.platform.code-server.version="${CODE_SERVER_VERSION}" \
      edu.platform.ttyd.version="${TTYD_VERSION}" \
      edu.platform.python.version="3.14.0" \
      edu.platform.gcc.version="12.2.0" \
      edu.platform.openjdk.version="17.0.21" \
      edu.platform.go.version="1.25.1" \
      edu.platform.workspace.capabilities="webide,terminal,snapshot,checkpoint,save-bridge" \
      edu.platform.workspace.contract="p16-c"

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
    WORKSPACE_TERMINAL_URL=http://127.0.0.1:7681 \
    WORKSPACE_ROUTER_ADDR=0.0.0.0:8080

RUN groupadd --gid 10001 workspace \
    && useradd --uid 10001 --gid workspace --home-dir /tmp/workspace-home --shell /bin/sh workspace \
    && mkdir -p /opt/workspace-config/User /opt/workspace-extensions /workspace \
    && printf '[]\n' > /opt/workspace-extensions/extensions.json \
    && chown workspace:workspace /workspace \
    && chmod 0555 /opt/workspace-extensions \
    && chmod 0444 /opt/workspace-extensions/extensions.json

COPY --from=code-server-downloader /opt/code-server /opt/code-server
COPY --from=ttyd-downloader /usr/local/bin/ttyd /usr/local/bin/ttyd
COPY --from=router-builder /out/workspace-router /usr/local/bin/workspace-router
COPY --from=router-builder /usr/local/go /usr/local/go
COPY --from=debug-tools-builder /out/dlv /out/gopls /usr/local/bin/
COPY requirements.lock /opt/workspace-requirements.lock
COPY entrypoint.sh /usr/local/bin/workspace-entrypoint
COPY settings.json /opt/workspace-config/User/settings.json
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
      gcc-12=12.2.0-14+deb12u1 \
      g++-12=12.2.0-14+deb12u1 \
      gdb=13.1-3 \
      openjdk-17-jdk-headless=17.0.21+9-1~deb12u1 \
    && ln -s /usr/bin/gcc-12 /usr/local/bin/gcc \
    && ln -s /usr/bin/g++-12 /usr/local/bin/g++ \
    && ln -s /usr/local/go/bin/go /usr/local/bin/go \
    && ln -s /usr/local/go/bin/gofmt /usr/local/bin/gofmt \
    && python -m pip install --no-cache-dir -r /opt/workspace-requirements.lock \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && chmod 0555 /usr/local/bin/workspace-router /usr/local/bin/workspace-entrypoint \
    && chmod 0444 /opt/workspace-config/User/settings.json

COPY go-workspace.sh /usr/local/bin/workspace-go
RUN rm /usr/local/bin/go \
    && ln -s /usr/local/bin/workspace-go /usr/local/bin/go \
    && chmod 0555 /usr/local/bin/workspace-go
COPY --from=debug-extensions-builder /opt/workspace-extensions /opt/workspace-extensions
COPY debug-extensions.lock.json /opt/debug-extensions.lock.json
COPY save-bridge /opt/workspace-save-bridge
RUN python /opt/workspace-save-bridge/package.py /tmp/edu-save-bridge.vsix \
    && /opt/code-server/bin/code-server \
      --user-data-dir /tmp/code-server-install \
      --extensions-dir /opt/workspace-extensions \
      --install-extension /tmp/edu-save-bridge.vsix \
    && rm -rf /opt/workspace-save-bridge /tmp/code-server-install /tmp/edu-save-bridge.vsix

ENV WORKSPACE_SAVE_BRIDGE_URL=http://127.0.0.1:3001 \
    GOMAXPROCS=2 \
    GOFLAGS=-p=2

USER 10001:10001
WORKDIR /workspace
EXPOSE 8080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
    CMD ["/usr/local/bin/workspace-router", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/workspace-entrypoint"]
