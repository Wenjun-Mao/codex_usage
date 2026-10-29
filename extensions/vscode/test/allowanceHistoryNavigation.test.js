const assert = require("node:assert/strict");
const test = require("node:test");
const { validateAllowanceHistory } = require("../out/allowanceHistoryNavigation");
const { DashboardNavigation } = require("../out/dashboardNavigation");
const { AgentRequestError } = require("../out/agentClient");
const { WEBVIEW_COMMANDS } = require("../out/reportHtml");
const manifest = require("../package.json");

const state = { period_page: 0, uncertain_page: 0, kind: "", index: -1, fit_page: 0, capture_page: 0, capture_order: "newest" };
const scope = "a".repeat(64);
const selected = { scope, state: { ...state, kind: "periods", index: 1 } };
const current = { scope, state, actions: [{ scope, state }, selected] };
const status = { ledger_revision: 2, plan_allowance: { probe_status: "fresh", active_buckets: [] } };

test("allowance history accepts exact private issued states and rejects crafted indices", () => {
  assert.equal(validateAllowanceHistory(selected, current), selected);
  for (const value of [null, [], { ...selected, extra: true }, { ...selected, scope: "b".repeat(64) },
    ...[{ index: true }, { index: -2 }, { period_page: 1 }, { capture_page: "0" }, { fit_page: 2**32 },
        { kind: "uncertain" }, { capture_order: "random" }, { series: "other" }].map(fields => ({ ...selected, state: { ...selected.state, ...fields } }))]) {
    assert.equal(validateAllowanceHistory(value, current), undefined);
  }
  assert(WEBVIEW_COMMANDS.includes("codexUsage.navigateAllowanceHistory"));
  assert(!manifest.contributes.commands.some(c => c.command === "codexUsage.navigateAllowanceHistory"));
  assert(!manifest.activationEvents.includes("onCommand:codexUsage.navigateAllowanceHistory"));
});

test("private history survives an older status but clears on revision, evidence, identity and reload", () => {
  for (const change of ["revision", "evidence", "identity", "reload"]) {
    const nav = new DashboardNavigation();
    nav.query(new URLSearchParams(), "all", status);
    nav.accept({ ledger_revision: 2, allowance_navigation: current });
    assert(nav.allowance(selected));
    const retained = new URLSearchParams();
    nav.query(retained, "all", { ...status, ledger_revision: 1 });
    assert.equal(retained.get("allowance_action"), JSON.stringify(selected));
    const query = new URLSearchParams();
    if (change === "reload") nav.reset();
    nav.query(query, change === "identity" ? "other" : "all", ["revision", "identity"].includes(change) ? { ...status, ledger_revision: 3 } :
      change === "evidence" ? { ...status, plan_allowance: { ...status.plan_allowance, probe_status: "stale" } } : status);
    assert(!query.has("allowance_action"));
  }
});

test("advertised load stays deferred through warm refreshes and theme; only explicit selection loads", () => {
  const nav = new DashboardNavigation();
  const invitation = { scope, state, actions: [{ scope, state }], deferred: true };
  for (const identity of ["night", "day", "auto", "range-other"]) {
    const query = new URLSearchParams();
    nav.query(query, identity, status);
    assert.equal(query.get("allowance_history"), "deferred");
    assert(!query.has("allowance_action"));
    nav.accept({ ledger_revision: 2, allowance_navigation: invitation });
  }
  assert(nav.allowance(invitation.actions[0]));
  const requested = new URLSearchParams();
  nav.query(requested, "range-other", status);
  assert.equal(requested.get("allowance_history"), "requested");
  assert.equal(requested.get("allowance_action"), JSON.stringify(invitation.actions[0]));
  nav.accept({ ledger_revision: 2, allowance_navigation: current });
  assert(nav.allowance(selected));
  const filtered = new URLSearchParams();
  nav.query(filtered, "different-project-and-range", status);
  assert.equal(filtered.get("allowance_action"), JSON.stringify(selected));
  const fresh = new URLSearchParams();
  nav.query(fresh, "different-project-and-range", { ...status, ledger_revision: 3 });
  assert.equal(fresh.get("allowance_history"), "requested");
  assert(!fresh.has("allowance_action"));
  nav.reset(true);
  const reopened = new URLSearchParams();
  nav.query(reopened, "different-project-and-range", status);
  assert.equal(reopened.get("allowance_history"), "deferred");
});

test("a collector cannot silently ignore requested deferred mode", async () => {
  const nav = new DashboardNavigation();
  for (const report of [{ ledger_revision: 2 }, { ledger_revision: 2, allowance_navigation: current }]) {
    await assert.rejects(nav.report({ get: async () => report },
      new URLSearchParams({ allowance_history: "deferred" })), /requested allowance history mode/);
  }
});

test("chart-only expiry preserves valid history; independently expired history recovers once", async () => {
  for (const both of [false, true]) {
    const nav = new DashboardNavigation();
    const paths = [];
    const query = new URLSearchParams({ allowance_history: 'requested', allowance_action: JSON.stringify(selected), breakdown_action: 'issued' });
    const result = { ledger_revision: 2, allowance_navigation: current };
    await nav.report({ get: async path => {
      paths.push(new URLSearchParams(path.split('?')[1]));
      if (paths.length === 1) throw new AgentRequestError('calendar changed', 409, 'breakdown_scope_expired');
      if (both && paths.length === 2) throw new AgentRequestError('evidence changed', 409, 'allowance_scope_expired');
      return result;
    } }, query);
    assert.equal(paths[1].get('allowance_action'), JSON.stringify(selected));
    assert(!paths[1].has('breakdown_action'));
    assert.equal(paths.length, both ? 3 : 2);
    if (both) assert(!paths[2].has('allowance_action'));
    assert.equal(paths.at(-1).get('allowance_history'), 'requested');
  }
});

test("private allowance expiry recovers once without losing filters; crafted requests never recover", async () => {
  const nav = new DashboardNavigation();
  const paths = [];
  const result = { ledger_revision: 3 };
  const query = new URLSearchParams({ range: "all", project_key: "p", allowance_action: JSON.stringify(selected), breakdown_action: "other", speed_window_scope: "other" });
  const report = await nav.report({ get: async path => {
    paths.push(path);
    if (paths.length === 1) throw new AgentRequestError("expired", 409, "allowance_scope_expired");
    return result;
  } }, query);
  assert.equal(report, result);
  assert.equal(paths.length, 2);
  const fresh = new URLSearchParams(paths[1].split("?")[1]);
  assert.equal(fresh.get("project_key"), "p");
  assert.equal(fresh.get("range"), "all");
  assert(!fresh.has("allowance_action") && !fresh.has("breakdown_action") && !fresh.has("speed_window_scope"));
  for (const error of [new AgentRequestError("unissued", 400), new AgentRequestError("other", 409, "other")]) {
    let calls = 0;
    await assert.rejects(nav.report({ get: async () => { calls++; throw error; } }, query), e => e === error);
    assert.equal(calls, 1);
  }
});
