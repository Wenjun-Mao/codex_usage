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
    nav.query(query, change === "identity" ? "other" : "all", change === "revision" ? { ...status, ledger_revision: 3 } :
      change === "evidence" ? { ...status, plan_allowance: { ...status.plan_allowance, probe_status: "stale" } } : status);
    assert(!query.has("allowance_action"));
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
