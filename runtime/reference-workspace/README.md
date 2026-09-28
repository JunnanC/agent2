# Reference workspace image

This image is a fixed, non-root contract fixture for local Swarm acceptance. It
binds only to port `8080`, exposes `/healthz`, `/webide/`, `/notebook/`,
`/terminal/`, and `/preview/`, and supports HTTP and WebSocket requests. The
production image may replace the contract implementation with the approved
WebIDE, Jupyter, terminal, and preview components without changing the adapter
or gateway contract.
