const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { AgentClient, AgentRequestError } = require("../out/agentClient");
const { DashboardNavigation } = require("../out/dashboardNavigation");

test("authenticated transport recovers pruned R1 scope under cached R1 status; malformed commands never retry", async () => {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), "breakdown-recovery-"));
  const token = "e".repeat(40);
  const state = { basis: "selected", view: "hour", metric: "tokens", group: "model", day: "2026-10-09", detail: "" };
  const action = { scope: "a".repeat(64), state };
  const r2 = { ledger_revision: 2, breakdown_navigation: { scope: "b".repeat(64), state, actions: [] } };
  const calls = [];
  const server = http.createServer((request, response) => {
    assert.equal(request.headers.authorization, `Bearer ${token}`);
    const query = new URL(request.url, "http://localhost");
    response.setHeader("Content-Type", "application/json");
    if (query.pathname === "/v1/health") return response.end(JSON.stringify({ ok: true, api_version: 1 }));
    calls.push(request.url);
    const sent = query.searchParams.get("breakdown_action");
    if (!sent) return response.end(JSON.stringify(r2));
    const issued = sent === JSON.stringify(action);
    response.statusCode = issued ? 409 : 400;
    response.end(JSON.stringify(issued ? { error: "Issued scope expired", code: "breakdown_scope_expired" } : { error: "Unissued" }));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    await fs.mkdir(path.join(home, ".codex-usage"));
    await fs.writeFile(path.join(home, ".codex-usage/agent.json"), JSON.stringify({
      pid: process.pid, api_version: 1, port: server.address().port, token, codex_home: home,
    }));
    const client = await AgentClient.discoverAt(home);
    const navigation = new DashboardNavigation();
    const cached = { ledger_revision: 1, plan_allowance: { probe_status: "fresh", active_buckets: [] } };
    navigation.query(new URLSearchParams(), "today", cached);
    navigation.accept({ ledger_revision: 1, breakdown_navigation: { scope: action.scope, state, actions: [action] } });
    assert(navigation.breakdown(action));
    const query = new URLSearchParams({ range: "today" });
    navigation.query(query, "today", cached);
    assert.equal(query.get("breakdown_action"), JSON.stringify(action));
    assert.deepEqual(await navigation.report(client, query), r2);
    assert.equal(calls.length, 2);
    assert.equal(calls[1], "/v1/report?range=today");
    const bad = new URLSearchParams({ range: "today", breakdown_action: JSON.stringify({ ...action, extra: true }) });
    await assert.rejects(navigation.report(client, bad), error => error instanceof AgentRequestError && error.status === 400);
    assert.equal(calls.length, 3);
  } finally {
    await new Promise(resolve => server.close(resolve));
    await fs.rm(home, { recursive: true, force: true });
  }
});
