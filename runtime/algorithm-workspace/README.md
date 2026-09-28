# Local algorithm workspace image

This is the first local P14 image. It is intentionally small: a non-root Python
workspace contract server and the Python interpreter used by one-shot judge
containers. The runtime worker applies the stronger read-only, capability and
resource limits when creating containers.

The workspace contract exposes `/healthz`, `/webide/`, `/terminal/`, and
`/preview/` on port 8080. The image runs as `workspace`; no host port is
published. Judge containers use the same interpreter with a read-only rootfs,
an isolated read-only source volume, and `network=none`.
