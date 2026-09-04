const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { AgentClient, resolveCodexHome, samePath, settingsFilePath } = require("../out/agentClient");

test("settings path and custom Codex home follow the shared contract", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "codex-usage-companion-"));
  const data = path.join(root, "config");
  const home = path.join(root, "custom-home");
  await fs.mkdir(data, { recursive: true });
  await fs.writeFile(path.join(data, "settings.json"), JSON.stringify({ codex_home: home }));

  assert.equal(settingsFilePath({ CODEX_USAGE_DATA_DIR: data }), path.join(data, "settings.json"));
  assert.equal(await resolveCodexHome({ CODEX_USAGE_DATA_DIR: data }), path.resolve(home));
});

test("descriptor home comparison follows Windows path casing", () => {
  assert.equal(samePath("C:\\Users\\Test\\.codex", "c:\\users\\test\\.CODEX", "win32"), true);
  assert.equal(samePath("/Users/Test/.codex", "/users/test/.codex", "darwin"), false);
});

test("agent discovery authenticates health and subsequent requests", async (context) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "codex-usage-companion-"));
  const data = path.join(root, "config");
  const home = path.join(root, ".codex");
  const token = "a".repeat(40);
  await fs.mkdir(path.join(home, ".codex-usage"), { recursive: true });
  await fs.mkdir(data, { recursive: true });
  await fs.writeFile(path.join(data, "settings.json"), JSON.stringify({ codex_home: home }));
  const seen = [];
  const server = http.createServer((request, response) => {
    seen.push({ url: request.url, authorization: request.headers.authorization, origin: request.headers.origin });
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(request.url === "/v1/health" ? { ok: true, api_version: 1 } : { ready: true }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const port = server.address().port;
  await fs.writeFile(path.join(home, ".codex-usage", "agent.json"), JSON.stringify({ pid: process.pid, api_version: 1, port, token, codex_home: home }));

  const previous = process.env.CODEX_USAGE_DATA_DIR;
  process.env.CODEX_USAGE_DATA_DIR = data;
  context.after(() => {
    if (previous === undefined) delete process.env.CODEX_USAGE_DATA_DIR;
    else process.env.CODEX_USAGE_DATA_DIR = previous;
  });
  const client = await AgentClient.discover();
  assert.deepEqual(await client.get("/v1/status"), { ready: true });
  assert.equal(seen.length, 2);
  assert.ok(seen.every((request) => request.authorization === `Bearer ${token}`));
  assert.ok(seen.every((request) => request.origin === undefined));
});

test("client rejects request smuggling paths and oversized request bodies", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "codex-usage-companion-"));
  const data = path.join(root, "config");
  const home = path.join(root, ".codex");
  const token = "b".repeat(40);
  await fs.mkdir(path.join(home, ".codex-usage"), { recursive: true });
  await fs.mkdir(data, { recursive: true });
  await fs.writeFile(path.join(data, "settings.json"), JSON.stringify({ codex_home: home }));
  const server = http.createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ ok: true, api_version: 1 }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await fs.writeFile(path.join(home, ".codex-usage", "agent.json"), JSON.stringify({ pid: process.pid, api_version: 1, port, token, codex_home: home }));
  const previous = process.env.CODEX_USAGE_DATA_DIR;
  process.env.CODEX_USAGE_DATA_DIR = data;
  try {
    const client = await AgentClient.discover();
    await assert.rejects(client.get("/v1/status\r\nInjected: value"), /Invalid collector request path/);
    await assert.rejects(client.post("/v1/settings", { value: "x".repeat(2 * 1024 * 1024) }), /request body exceeds/);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    if (previous === undefined) delete process.env.CODEX_USAGE_DATA_DIR;
    else process.env.CODEX_USAGE_DATA_DIR = previous;
  }
});
