const assert = require("node:assert/strict");
const test = require("node:test");
const { DashboardNavigation } = require("../out/dashboardNavigation");
const { AgentRequestError } = require("../out/agentClient");

test("an older cached status cannot invalidate a newer rendered navigation scope", () => {
  const navigation = new DashboardNavigation();
  const state = { basis: "cycle", view: "hour", metric: "cost", group: "model", day: "2026-10-09", detail: "" };
  const action = { scope: "a".repeat(64), state: { ...state, metric: "tokens" } };
  const status = { ledger_revision: 1, plan_allowance: { probe_status: "stale", active_buckets: [] } };
  navigation.query(new URLSearchParams(), "all", status);
  navigation.accept({ ledger_revision: 2, breakdown_navigation: { scope: action.scope, state, actions: [action] } });
  assert(navigation.breakdown(action));
  const query = new URLSearchParams();
  navigation.query(query, "all", status);
  assert.equal(query.get("breakdown_action"), JSON.stringify(action));
  const newer = new URLSearchParams();
  navigation.query(newer, "all", { ...status, ledger_revision: 3 });
  assert.equal(newer.get("breakdown_action"), null);
});

test("deadline expiry clears a current-cycle command without a new revision", () => {
  const navigation = new DashboardNavigation();
  const state = { basis: "cycle", view: "hour", metric: "tokens", group: "model", day: "2026-10-09", detail: "" };
  const action = { scope: "a".repeat(64), state };
  const status = { ledger_revision: 2, plan_allowance: { probe_status: "fresh", active_buckets: [{ duration_minutes: 10080, resets_at: Date.now()/1000 + 100 }] } };
  navigation.query(new URLSearchParams(), "all", status);
  navigation.accept({ ledger_revision: 2, breakdown_navigation: { scope: action.scope, state, actions: [action] } });
  assert(navigation.breakdown(action));
  const query = new URLSearchParams();
  navigation.query(query, "all", { ...status, plan_allowance: { ...status.plan_allowance, active_buckets: [{ duration_minutes: 10080, resets_at: 100 }] } });
  assert.equal(query.get("breakdown_action"), null);
});

test("fresh-to-stale invalidates issued evidence scope even for Selected range", () => {
  const navigation = new DashboardNavigation();
  const state = { basis: "selected", view: "hour", metric: "tokens", group: "model", day: "2026-10-09", detail: "" };
  const action = { scope: "a".repeat(64), state };
  const status = { ledger_revision: 2, plan_allowance: { probe_status: "fresh", active_buckets: [] } };
  navigation.query(new URLSearchParams(), "all", status);
  navigation.accept({ ledger_revision: 2, breakdown_navigation: { scope: action.scope, state, actions: [action] } });
  assert(navigation.breakdown(action));
  const valid = new URLSearchParams();
  navigation.query(valid, "all", status);
  assert.equal(valid.get("breakdown_action"), JSON.stringify(action));
  const stale = new URLSearchParams();
  navigation.query(stale, "all", { ...status, plan_allowance: { ...status.plan_allowance, probe_status: "stale" } });
  assert.equal(stale.has("breakdown_action"), false);
});

for (const scenario of ["selected expiry", "midnight", "timezone", "transitions", "other client pruned R1 report"]) {
  test(`${scenario}: one typed scope-expiry recovery clears chart state without changing filters`, async () => {
    const navigation = new DashboardNavigation();
    const calls = [];
    const report = { ledger_revision: 2 };
    const client = { get: async path => {
      calls.push(path);
      if (calls.length === 1) throw new AgentRequestError("expired", 409, "breakdown_scope_expired");
      return report;
    } };
    const query = new URLSearchParams({ range: "today", project_key: "p", breakdown_action: "issued", speed_window_scope: "expired" });
    assert.equal(await navigation.report(client, query), report);
    assert.equal(calls.length, 2);
    const recovered = new URLSearchParams(calls[1].split("?")[1]);
    assert.equal(recovered.get("range"), "today");
    assert.equal(recovered.get("project_key"), "p");
    assert.equal(recovered.has("breakdown_action"), false);
    assert.equal(recovered.has("speed_window_scope"), false);
  });
}

test("malformed, unissued and generic failures never trigger bare-report retry", async () => {
  for (const error of [new AgentRequestError("bad", 400), new AgentRequestError("conflict", 409, "other"), new Error("failure")]) {
    const navigation = new DashboardNavigation();
    let calls = 0;
    await assert.rejects(navigation.report({ get: async () => { calls++; throw error; } },
      new URLSearchParams({ breakdown_action: "bad" })), e => e === error);
    assert.equal(calls, 1);
  }
});

test("explicit Reload clears retained commands even if receipt retention has elapsed", () => {
  const navigation = new DashboardNavigation();
  const state = { basis: "selected", view: "hour", metric: "tokens", group: "model", day: "2026-10-09", detail: "" };
  const action = { scope: "a".repeat(64), state };
  const status = { ledger_revision: 1, plan_allowance: { probe_status: "stale", active_buckets: [] } };
  navigation.query(new URLSearchParams(), "all", status);
  navigation.accept({ ledger_revision: 1, breakdown_navigation: { scope: action.scope, state, actions: [action] } });
  assert(navigation.breakdown(action));
  const retained = new URLSearchParams();
  navigation.query(retained, "all", status);
  assert(retained.has("breakdown_action"));
  navigation.reset();
  const reload = new URLSearchParams();
  navigation.query(reload, "all", status);
  assert(!reload.has("breakdown_action"));
});
