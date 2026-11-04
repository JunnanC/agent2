const assert = require("node:assert/strict");
const http = require("node:http");
const Module = require("node:module");

const documents = [
  { isDirty: true, uri: { scheme: "file", path: "/workspace/main.py" } },
  { isDirty: true, uri: { scheme: "file", path: "/workspace/README.md" } },
];
let saveAllCalls = 0;
const vscode = {
  workspace: {
    textDocuments: documents,
    asRelativePath: (uri) => uri.path.replace("/workspace/", ""),
    saveAll: async (includeUntitled) => {
      assert.equal(includeUntitled, false);
      saveAllCalls += 1;
      documents.forEach((document) => { document.isDirty = false; });
      return true;
    },
  },
};
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  return request === "vscode" ? vscode : originalLoad.call(this, request, parent, isMain);
};
process.env.WORKSPACE_SAVE_BRIDGE_PORT = "3002";
const extensionPath = process.env.EDU_SAVE_BRIDGE_EXTENSION || "../save-bridge/extension.js";
require(extensionPath).activate({ subscriptions: [] });

function post(path, origin = "http://127.0.0.1:8080") {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      request_id: "bridge-test-1",
      session_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    });
    const request = http.request({
      host: "127.0.0.1",
      port: 3002,
      path,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
        Origin: origin,
        "X-Forwarded-Host": "127.0.0.1:8080",
        "X-Edu-Origin": "http://127.0.0.1:8080",
        "X-Workspace-Session": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      },
    }, (response) => {
      let value = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { value += chunk; });
      response.on("end", () => resolve({ status: response.statusCode, body: JSON.parse(value) }));
    });
    request.on("error", reject);
    request.end(body);
  });
}

(async () => {
  try {
    const status = await post("/status");
    assert.equal(status.status, 200);
    assert.deepEqual(status.body.dirty_files, ["README.md", "main.py"]);
    assert.equal(status.body.saved, null);

    const saved = await post("/save");
    assert.equal(saved.status, 200);
    assert.equal(saved.body.request_id, "bridge-test-1");
    assert.equal(saved.body.session_id, "01ARZ3NDEKTSV4RRFFQ69G5FAV");
    assert.equal(saved.body.saved, true);
    assert.deepEqual(saved.body.dirty_files, []);
    assert.equal(saveAllCalls, 1);

    const rejected = await post("/status", "http://attacker.invalid");
    assert.equal(rejected.status, 403);

    // Reconnection may start a new host while the disconnected host holds the port.
    documents[0].isDirty = true;
    vscode.workspace.saveAll = () => new Promise(() => {});
    const currentDocuments = [
      { isDirty: true, uri: { scheme: "file", path: "/workspace/current.py" } },
    ];
    const currentVscode = {
      workspace: { ...vscode.workspace, textDocuments: currentDocuments,
        saveAll: async () => { currentDocuments[0].isDirty = false; return true; } },
    };
    Module._load = function (request, parent, isMain) {
      return request === "vscode" ? currentVscode : originalLoad.call(this, request, parent, isMain);
    };
    delete require.cache[require.resolve(extensionPath)];
    require(extensionPath).activate({ subscriptions: [] });
    const disconnectedSave = await post("/save");
    assert.equal(disconnectedSave.status, 503);
    assert.equal(documents[0].isDirty, true);
    let currentStatus;
    for (let attempt = 0; attempt < 20; attempt++) {
      try { currentStatus = await post("/status"); break; } catch {}
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.deepEqual(currentStatus.body.dirty_files, ["current.py"]);
    assert.equal((await post("/save")).body.saved, true);
    assert.equal(documents[0].isDirty, true);
    process.stdout.write("save bridge protocol passed\n");
    process.exit(0);
  } catch (error) {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
  }
})();
