const assert = require("node:assert/strict");
const test = require("node:test");
const { DashboardNavigation } = require("../out/dashboardNavigation");

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
  const status = { ledger_revision: 2, plan_allowance: { probe_status: "fresh", active_buckets: [{ duration_minutes: 10080, resets_at: 100 }] } };
  navigation.query(new URLSearchParams(), "all", status);
  navigation.accept({ ledger_revision: 2, breakdown_navigation: { scope: action.scope, state, actions: [action] } });
  assert(navigation.breakdown(action));
  const query = new URLSearchParams();
  navigation.query(query, "all", status);
  assert.equal(query.get("breakdown_action"), null);
});
