const assert = require("node:assert/strict");
const test = require("node:test");
const { validateBreakdownNavigation } = require("../out/breakdownNavigation");

test("breakdown accepts only exact server-issued current-scope states", () => {
  const state = { basis: "cycle", view: "hour", metric: "tokens", group: "model", day: "2026-10-09", detail: "" };
  const action = { scope: "a".repeat(64), state };
  const nav = { scope: action.scope, state, actions: [action] };
  assert.deepEqual(validateBreakdownNavigation(action, nav), action);
  for (const value of [null, [], { ...action, extra: 1 }, { ...action, scope: "b".repeat(64) },
    { ...action, state: { ...state, day: "2026-10-10" } }, { ...action, state: { ...state, extra: 1 } },
    { ...action, state: { ...state, detail: "project:foreign" } }, { ...action, state: { ...state, metric: 1 } }]) {
    assert.equal(validateBreakdownNavigation(value, nav), undefined);
  }
});
