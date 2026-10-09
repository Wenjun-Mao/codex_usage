const test = require("node:test");
const assert = require("node:assert/strict");
const { validateSpeedNavigation, chartQuery } = require("../out/speedNavigation");
const { chooseProjects } = require("../out/projectSelection");
const { usageStatusFingerprint } = require("../out/usageRefreshPolicy");

const nav = { scope: "a".repeat(64), granularity: "daily", min_date: "2026-09-09", max_date: "2026-10-08", window_start: "2026-10-02", previous: "2026-09-25", next: null };
const valid = { scope: nav.scope, granularity: "hourly", windowStart: nav.previous };

test("chart commands validate shape, types, dates, visible scope and permitted neighbors", () => {
  assert.deepEqual(validateSpeedNavigation(valid, nav), { granularity: "hourly", windowStart: nav.previous });
  for (const args of [null, [], "hourly", { ...valid, scope: "b".repeat(64) }, { ...valid, granularity: "weekly" }, { ...valid, windowStart: "2026-09-32" }, { ...valid, windowStart: "2026-09-26" }, { ...valid, windowStart: "1900-01-01" }, { ...valid, extra: true }]) {
    assert.equal(validateSpeedNavigation(args, nav), undefined);
  }
  assert.equal(validateSpeedNavigation(valid, undefined), undefined);
});

test("chart query carries state without changing global filters", () => {
  const query = new URLSearchParams({ range: "30d", project_key: "project" });
  chartQuery(query, { granularity: "hourly", windowStart: nav.previous }, nav.scope);
  assert.equal(query.get("range"), "30d");
  assert.equal(query.get("project_key"), "project");
  assert.equal(query.get("speed_window_start"), nav.previous);
  assert.equal(query.get("speed_window_scope"), nav.scope);
});

test("latest week is an explicit validated jump, not arbitrary in-range navigation", () => {
  const older = { ...nav, granularity: "hourly", window_start: "2026-09-18", previous: "2026-09-11", next: "2026-09-25" };
  const latest = { scope: nav.scope, granularity: "hourly", windowStart: "2026-10-02" };
  assert.deepEqual(validateSpeedNavigation(latest, older), { granularity: "hourly", windowStart: "2026-10-02" });
  for (const args of [{ ...latest, windowStart: "2026-10-01" }, { ...latest, scope: "b".repeat(64) }, { ...latest, extra: true }]) {
    assert.equal(validateSpeedNavigation(args, older), undefined);
  }
  assert.equal(validateSpeedNavigation({ ...latest, windowStart: older.previous }, nav), undefined);
  const short = { ...nav, min_date: "2026-10-06", window_start: "2026-10-07", previous: null };
  assert.deepEqual(validateSpeedNavigation({ ...latest, windowStart: "2026-10-06" }, short), { granularity: "hourly", windowStart: "2026-10-06" });
});

test("explicit All Projects stays unfiltered while selected-all remains fixed", async () => {
  const projects = [{ project_key: "a", project_label: "Same", task_count: 1 }, { project_key: "b", project_label: "Same", task_count: 2 }];
  assert.deepEqual(await chooseProjects(projects, ["a"], async () => "all", async () => { throw Error("unexpected subset"); }), []);
  const fixed = await chooseProjects(projects, [], async () => "subset", async (choices) => choices);
  assert.deepEqual(fixed, ["a", "b"]);
  projects.push({ project_key: "future", project_label: "New", task_count: 1 });
  assert.deepEqual(fixed, ["a", "b"]);
  assert.equal(await chooseProjects(projects, fixed, async () => undefined, async () => []), undefined);
  assert.equal(await chooseProjects(projects, fixed, async () => "subset", async () => undefined), undefined);
  assert.deepEqual(await chooseProjects(projects, fixed, async () => "subset", async () => []), []);
});

test("timing-only revisions trigger refresh and optional legacy status remains readable", () => {
  const status = { ledger_revision: 1, coverage: { complete: true, fraction: 1, stale_sources: 0, pending_files: 0, pending_bytes: 0 } };
  const legacy = usageStatusFingerprint(status);
  assert.equal(usageStatusFingerprint({ ...status }), legacy);
  assert.notEqual(usageStatusFingerprint({ ...status, speed: { revision: 1, metric_version: 1 } }), usageStatusFingerprint({ ...status, speed: { revision: 2, metric_version: 1 } }));
});
