# Algorithm workspace image

This workspace provides code-server 4.104.2 and Python
3.14.0 for Linux AMD64. Both the final base image and the Go builder are pinned
by platform-specific OCI manifest digest; the code-server archive is pinned by
SHA-256. The final image installs no mutable operating-system packages during
its build.

The public container contract is deliberately narrow:

- `GET /healthz` reports readiness without returning runtime details (it probes
  code-server only; ttyd has no health endpoint).
- `/webide/` proxies HTTP, static assets, and WebSocket upgrades to code-server.
- `/terminal/` proxies HTTP and WebSocket upgrades to the pinned ttyd binary
  (`--base-path /terminal`, listening only on `127.0.0.1:7681`); the router keeps
  the `/terminal/` prefix upstream, so gateway paths map directly onto ttyd. ttyd
  runs `/bin/bash` writable inside the workspace as UID 10001.
- `/notebook/` and `/preview/` are not platform capabilities.
- code-server listens only on `127.0.0.1:3000`; the router listens on `8080`.
- every `/webide/` and `/terminal/` request requires `X-Workspace-Upstream-Token`.
  The router reads the expected value from `/run/secrets/workspace_upstream_token`,
  uses a constant-time digest comparison, and removes the header before proxying.

The image runs as UID/GID `10001`, expects `/workspace` to be a task-scoped
volume, keeps HOME/XDG/user-data under `/tmp`, and keeps the extension directory
read-only. The runtime must provide a read-only root filesystem, tmpfs mounts
for `/tmp` and `/run` as needed, the token secret, and the normal capability,
resource, PID, network, and TTL controls. No host port should be published.
An explicit container command is passed through unchanged so the existing
one-shot Python judge can continue to use this environment image.

Run the image-only acceptance gate from the repository root:

```powershell
./scripts/verify/workspace-image.ps1
```

The script builds and tests only through Docker, then writes image metadata,
smoke results, size, digests, user, entrypoint, and an SPDX JSON SBOM under
`evidence/workspace-image/`. The full image gate requires the `docker sbom`
plugin. Registry promotion and Swarm deployment need separate acceptance;
their entry points and prerequisites are in the [script inventory](../../scripts/README.md).
