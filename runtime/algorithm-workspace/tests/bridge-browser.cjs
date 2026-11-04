// Real code-server saveAll/dirty/reload check. Starts only its own Docker container.
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const http = require("node:http");
const { chromium } = require(require.resolve("@playwright/test", {
  paths: [path.resolve(__dirname, "../../../frontend")],
}));

const evidence = fs.mkdtempSync(path.join(os.tmpdir(), "edu-ide-bridge-"));
const name = `edu-ide-bridge-${crypto.randomBytes(6).toString("hex")}`;
const token = crypto.randomBytes(48).toString("hex");
const secret = path.join(evidence, "test-token");
fs.writeFileSync(secret, token);
const docker = (...args) => execFileSync("docker", args, { encoding: "utf8" }).trim();
let browser;
let page;
let started = false;
let proxy;

(async () => {
  try {
    docker("run", "--detach", "--name", name, "--read-only", "--cap-drop", "ALL",
      "--security-opt", "no-new-privileges:true", "--pids-limit", "256", "--memory", "1g",
      "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m,uid=10001,gid=10001",
      "--tmpfs", "/workspace:rw,exec,nosuid,nodev,size=64m,uid=10001,gid=10001",
      "--mount", `type=bind,source=${secret},target=/run/secrets/workspace_upstream_token,readonly`,
      "--publish", "127.0.0.1::8080", process.env.IDE_RUNTIME_IMAGE || "experimental-platform-workspace:local");
    started = true;
    docker("exec", name, "python", "-c", "open('/workspace/main.py','w').write('# original\\n')");
    const port = JSON.parse(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))["8080/tcp"][0].HostPort;
    const session = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
    // Simulate only the gateway's authenticated header injection, including WS
    // and service-worker traffic, which browser extraHTTPHeaders do not cover.
    proxy = http.createServer();
    const headers = (request) => ({ ...request.headers,
      "x-workspace-upstream-token": token, "x-workspace-session": session,
      "x-edu-origin": request.headers.origin || "",
    });
    proxy.on("request", (request, response) => {
      const upstream = http.request({ host: "127.0.0.1", port, path: request.url,
        method: request.method, headers: headers(request) }, (result) => {
        response.writeHead(result.statusCode, result.headers);
        result.pipe(response);
      });
      upstream.on("error", () => { response.writeHead(502); response.end(); });
      request.pipe(upstream);
    });
    proxy.on("upgrade", (request, socket, head) => {
      const upstream = http.request({ host: "127.0.0.1", port, path: request.url,
        method: request.method, headers: headers(request) });
      upstream.on("upgrade", (response, remote, remoteHead) => {
        socket.write(`HTTP/1.1 ${response.statusCode} ${response.statusMessage}\r\n`);
        for (const [key, value] of Object.entries(response.headers)) socket.write(`${key}: ${value}\r\n`);
        socket.write("\r\n");
        if (remoteHead.length) socket.write(remoteHead);
        if (head.length) remote.write(head);
        socket.pipe(remote).pipe(socket);
        socket.on("error", () => remote.destroy());
        remote.on("error", () => socket.destroy());
      });
      upstream.on("error", () => socket.destroy());
      upstream.end();
    });
    await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));
    const base = `http://127.0.0.1:${proxy.address().port}`;
    browser = await chromium.launch({ executablePath: process.env.IDE_BROWSER_EXECUTABLE || undefined });
    const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
    page = await context.newPage();
    for (let n = 0; n < 60; n++) {
      try { if ((await page.request.get(`${base}/healthz`)).ok()) break; } catch {}
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    await page.goto(`${base}/webide/?folder=/workspace`);
    await page.locator(".monaco-workbench").waitFor({ timeout: 60000 });
    await page.locator(".monaco-workbench").click({ position: { x: 500, y: 60 } });
    await page.keyboard.press("Control+p");
    await page.locator(".quick-input-widget input").fill("main.py");
    await page.locator(".quick-input-list .monaco-list-row").filter({ hasText: "main.py" }).first().waitFor();
    await page.keyboard.press("Enter");
    await page.locator(".monaco-editor .view-lines").first().click();
    await page.keyboard.press("Control+End");
    await page.keyboard.type("\nprint('saved-through-bridge')\n");
    const post = (action, overrides = {}) => page.request.post(`${base}/webide/edu-control/${action}`, {
      headers: { Origin: base }, data: { request_id: "real-browser-check", session_id: session, ...overrides },
    });
    let status;
    for (let n = 0; n < 60; n++) {
      const response = await post("status");
      if (response.ok()) { status = await response.json(); break; }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    assert(status, "real extension host did not activate");
    assert(status.dirty_files.includes("main.py"), JSON.stringify(status));
    assert.equal((await post("reload")).status(), 409);
    assert.equal((await post("status", { session_id: "01ARZ3NDEKTSV4RRFFQ69G5FAA" })).status(), 403);
    const saved = await (await post("save")).json();
    assert.equal(saved.saved, true, JSON.stringify(saved));
    assert.deepEqual(saved.dirty_files, []);
    assert(docker("exec", name, "cat", "/workspace/main.py").includes("saved-through-bridge"));
    docker("exec", name, "python", "-c", "open('/workspace/main.py','w').write('# restored-from-baseline\\n')");
    const [, reload] = await Promise.all([page.waitForEvent("framenavigated"), post("reload")]);
    assert.equal(reload.status(), 200);
    await page.locator(".monaco-workbench").waitFor();
    await page.getByText("# restored-from-baseline", { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(evidence, "code-server.png") });
    fs.writeFileSync(path.join(evidence, "result.json"), JSON.stringify({
      result: "passed", real_extension_host: true, dirty: status, saved,
      session_mismatch_rejected: true, reload: true,
      image: docker("inspect", "--format", "{{.Image}}", name),
    }, null, 2));
    process.stdout.write(`Real IDE bridge passed. Evidence: ${evidence}\n`);
  } catch (error) {
    if (page) {
      await page.screenshot({ path: path.join(evidence, "failure.png") });
      fs.writeFileSync(path.join(evidence, "failure.txt"), await page.locator("body").innerText());
    }
    process.stderr.write(`Failed browser evidence: ${evidence}\n`);
    throw error;
  } finally {
    if (browser) await browser.close();
    if (proxy) proxy.close();
    if (started) docker("rm", "--force", name);
    fs.unlinkSync(secret);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
