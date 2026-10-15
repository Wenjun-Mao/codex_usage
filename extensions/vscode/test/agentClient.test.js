const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { AgentClient, resolveCodexHome, samePath, settingsFilePath } = require("../out/agentClient");
const compatibleHealth = { ok: true, api_version: 1, capabilities: ["physical-lineage-accounting-v2"] };

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
    response.end(JSON.stringify(request.url === "/v1/health" ? compatibleHealth : { ready: true }));
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

test("default keep-alive socket timeouts do not limit ledger reads or capture writes", async context => {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), "codex-usage-timeout-"));
  const descriptorPath = path.join(home, ".codex-usage", "agent.json");
  await fs.mkdir(path.dirname(descriptorPath));
  const server = http.createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(request.url === "/v1/health" ? compatibleHealth : { ready: true }));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const agent = new http.Agent({ keepAlive: true, maxSockets: 1, timeout: 5000 });
  const original = http.request;
  const requests = [];
  http.request = (options, onResponse) => {
    const request = original({ ...options, agent }, onResponse);
    request.once("finish", () => requests.push({
      path: options.path, timeout: request.socket.timeout, reused: request.reusedSocket,
    }));
    return request;
  };
  context.after(async () => {
    http.request = original;
    agent.destroy();
    await new Promise(resolve => server.close(resolve));
    await fs.rm(home, { recursive: true, force: true });
  });
  await fs.writeFile(descriptorPath, JSON.stringify({ pid: process.pid, api_version: 1,
    port: server.address().port, token: "t".repeat(40), codex_home: home }));
  const client = await AgentClient.discoverAt(home);
  assert.deepEqual(await client.get("/v1/status"), { ready: true });
  assert.deepEqual(await client.post("/v1/capture"), { ready: true });
  assert.deepEqual(requests, [
    { path: "/v1/health", timeout: 2000, reused: false },
    { path: "/v1/status", timeout: 0, reused: true },
    { path: "/v1/capture", timeout: 0, reused: true },
  ]);
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
    response.end(JSON.stringify(compatibleHealth));
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

test("read-only requests refresh one replaced descriptor while POST requests never replay", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "codex-usage-companion-"));
  const home = path.join(root, ".codex");
  const descriptorPath = path.join(home, ".codex-usage", "agent.json");
  await fs.mkdir(path.dirname(descriptorPath), { recursive: true });

  const first = http.createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(request.url === "/v1/health" ? compatibleHealth : { stale: true }));
  });
  await new Promise((resolve) => first.listen(0, "127.0.0.1", resolve));
  await fs.writeFile(descriptorPath, JSON.stringify({
    pid: 1001,
    api_version: 1,
    port: first.address().port,
    token: "c".repeat(40),
    codex_home: home,
    process_owner: "background",
    parent_pid: null,
    launch_id: null,
  }));
  const client = await AgentClient.discoverAt(home);
  await new Promise((resolve) => first.close(resolve));

  const retriedRequests = [];
  const second = http.createServer((request, response) => {
    retriedRequests.push(request.url);
    if (request.url === "/v1/capture") {
      request.socket.destroy();
      return;
    }
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(request.url === "/v1/health" ? compatibleHealth : { ready: true }));
  });
  await new Promise((resolve) => second.listen(0, "127.0.0.1", resolve));
  await fs.writeFile(descriptorPath, JSON.stringify({
    pid: 1002,
    api_version: 1,
    port: second.address().port,
    token: "d".repeat(40),
    codex_home: home,
    process_owner: "background",
    parent_pid: null,
    launch_id: null,
  }));

  assert.deepEqual(await client.get("/v1/status"), { ready: true });
  assert.deepEqual(retriedRequests, ["/v1/health", "/v1/status"]);

  const replayedRequests = [];
  const third = http.createServer((request, response) => {
    replayedRequests.push(request.url);
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(compatibleHealth));
  });
  await new Promise((resolve) => third.listen(0, "127.0.0.1", resolve));
  await fs.writeFile(descriptorPath, JSON.stringify({
    pid: 1003,
    api_version: 1,
    port: third.address().port,
    token: "e".repeat(40),
    codex_home: home,
    process_owner: "background",
    parent_pid: null,
    launch_id: null,
  }));

  try {
    await assert.rejects(client.post("/v1/capture"), /agent|socket|connect/i);
    assert.deepEqual(replayedRequests, []);
  } finally {
    await new Promise((resolve) => second.close(resolve));
    await new Promise((resolve) => third.close(resolve));
  }
});
