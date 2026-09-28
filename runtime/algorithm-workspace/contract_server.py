import json


CAPABILITIES = {"webide", "terminal", "preview"}


async def app(scope, receive, send):
    path = scope.get("path", "")
    if scope.get("type") == "http" and path == "/healthz":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
        return
    parts = path.strip("/").split("/")
    capability = parts[0] if parts else ""
    if scope.get("type") == "websocket":
        if capability not in CAPABILITIES:
            await send({"type": "websocket.close", "code": 4404})
            return
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": json.dumps({"ready": capability})})
        while True:
            message = await receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await send({"type": "websocket.send", "text": message["text"]})
            elif message.get("bytes") is not None:
                await send({"type": "websocket.send", "bytes": message["bytes"]})
        return
    if capability not in CAPABILITIES:
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"not found"})
        return
    body = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Algorithm Workspace</title></head>"
        f"<body><main><h1>{capability.title()}</h1><p>Algorithm workspace is ready.</p></main></body></html>"
    ).encode()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"cache-control", b"no-store")],
    })
    await send({"type": "http.response.body", "body": body})

