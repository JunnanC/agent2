const http = require("http");
const vscode = require("vscode");

const sessionPattern = /^[0-9A-Z]{26}$/;
const requestPattern = /^[A-Za-z0-9_-]{1,64}$/;

function dirtyFiles() {
  return vscode.workspace.textDocuments
    .filter((document) => document.isDirty)
    .map((document) => document.uri.scheme === "file"
      ? vscode.workspace.asRelativePath(document.uri, false)
      : document.uri.toString())
    .sort();
}

function respond(response, status, body) {
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(JSON.stringify(body));
}

function activate(context) {
  console.log("edu-save-bridge activated");
  const server = http.createServer((request, response) => {
    if (request.method !== "POST" || !["/status", "/save", "/reload"].includes(request.url)) {
      respond(response, 404, { error: "not_found" });
      return;
    }
    const expectedOrigin = request.headers["x-edu-origin"];
    let origin = "";
    try {
      origin = new URL(request.headers.origin || "").origin;
    } catch {}
    if (!expectedOrigin || origin !== expectedOrigin) {
      respond(response, 403, { error: "origin_rejected" });
      return;
    }

    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1024) request.destroy();
    });
    request.on("end", async () => {
      let value;
      try {
        value = JSON.parse(body);
      } catch {
        respond(response, 400, { error: "invalid_request" });
        return;
      }
      if (
        !value ||
        Object.keys(value).sort().join(",") !== "request_id,session_id" ||
        !requestPattern.test(value.request_id) ||
        !sessionPattern.test(value.session_id)
      ) {
        respond(response, 400, { error: "invalid_request" });
        return;
      }
      if (value.session_id !== request.headers["x-workspace-session"]) {
        respond(response, 403, { error: "session_rejected" });
        return;
      }

      let saved = null;
      if (request.url === "/save") {
        let timer;
        const unresponsive = new Error("editor_unresponsive");
        try {
          saved = await Promise.race([
            vscode.workspace.saveAll(false),
            new Promise((_, reject) => {
              timer = setTimeout(() => reject(unresponsive), 5000);
            }),
          ]);
        } catch (error) {
          if (error !== unresponsive) {
            respond(response, 503, { error: "save_failed" });
            return;
          }
          // A disconnected extension host can retain the port during reconnect.
          // Release it so the current editor host can serve the retried save.
          server.close();
          response.setHeader("Connection", "close");
          respond(response, 503, { error: "editor_unresponsive" });
          return;
        } finally {
          clearTimeout(timer);
        }
      }
      const dirty = dirtyFiles();
      if (request.url === "/reload" && dirty.length) {
        respond(response, 409, { error: "unsaved_documents", dirty_files: dirty });
        return;
      }
      respond(response, 200, {
        schema_version: 1,
        request_id: value.request_id,
        session_id: value.session_id,
        dirty_files: dirty,
        saved: request.url === "/save" ? saved && dirty.length === 0 : null,
      });
      if (request.url === "/reload") {
        setTimeout(() => vscode.commands.executeCommand("workbench.action.reloadWindow"), 250);
      }
    });
  });
  let retry;
  const listen = () => server.listen(Number(process.env.WORKSPACE_SAVE_BRIDGE_PORT || 3001), "127.0.0.1");
  server.on("error", (error) => {
    if (error.code === "EADDRINUSE") retry = setTimeout(listen, 250);
    else console.error("edu-save-bridge:", error.code);
  });
  listen();
  context.subscriptions.push({ dispose: () => { clearTimeout(retry); server.close(); } });
}

function deactivate() {}

module.exports = { activate, deactivate };
