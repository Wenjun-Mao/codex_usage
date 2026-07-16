const assert = require("node:assert/strict");
const test = require("node:test");

const {
  formatTransferResult,
  taskAvailabilityLabel,
  taskStateLabel,
  taskTransferControlLabel,
  taskTransferMenuItems,
  transientStatusLabel,
} = require("../out/transferPresentation");

function issue(code, message = "technical detail") {
  return { code, message, thread_id: "task-1" };
}

function result(overrides = {}) {
  const issues = overrides.issues ?? [];
  const counts = {
    discovered: 0,
    selected: 0,
    remote: 0,
    pulled: 0,
    pushed: 0,
    unchanged: 0,
    conflicts: 0,
    issues: issues.length,
    ...overrides,
  };
  return {
    outcome: overrides.outcome ?? (issues.length > 0 ? "issue" : "completed"),
    counts: {
      discovered: counts.discovered,
      selected: counts.selected,
      remote: counts.remote,
      pulled: counts.pulled,
      pushed: counts.pushed,
      unchanged: counts.unchanged,
      conflicts: counts.conflicts,
      issues: counts.issues,
    },
    timings_ms: {
      discovery: 0,
      planning: 0,
      pull: 0,
      push: 0,
      index: 0,
      total: 0,
    },
    threads: [],
    pulled: Array.from({ length: counts.pulled }, (_, index) => `pulled-${index + 1}`),
    pushed: Array.from({ length: counts.pushed }, (_, index) => `pushed-${index + 1}`),
    issues,
  };
}

test("task transfer menu has no setup selection pause or resume concepts", () => {
  const empty = taskTransferMenuItems("");
  const configured = taskTransferMenuItems("/transfer");

  assert.equal(taskTransferControlLabel(), "Task Transfer ▾");
  assert.deepEqual(empty.map((item) => item.action), [
    "importTasks", "exportTasks", "reviewStatus", "chooseFolder",
  ]);
  assert.deepEqual(configured.map((item) => item.action), [
    "importTasks", "exportTasks", "reviewStatus", "changeFolder", "openFolder", "forgetFolder",
  ]);
  const copy = JSON.stringify([...empty, ...configured]);
  assert.doesNotMatch(copy, /setup|required|pause|resume|selected/i);
  assert.match(copy, /Import Tasks/);
  assert.match(copy, /Export Tasks/);
  assert.match(copy, /Review Transfer Status/);
  assert.match(copy, /Transfer Folder/);
});

test("availability and planner states use task transfer language", () => {
  assert.equal(taskAvailabilityLabel("local"), "On this computer");
  assert.equal(taskAvailabilityLabel("remote"), "In transfer folder");
  assert.equal(taskAvailabilityLabel("both"), "On both");
  assert.equal(taskStateLabel("pull", "remote_only"), "Ready to import");
  assert.equal(taskStateLabel("push", "local_only"), "Ready to export");
  assert.equal(taskStateLabel("none", "synced"), "Up to date");
  assert.equal(taskStateLabel("conflict", "conflict"), "Conflict");
  assert.equal(taskStateLabel("issue", "missing"), "Missing");
});

test("transient states use usage-status Task Transfer wording", () => {
  assert.equal(transientStatusLabel("checking"), "Checking tasks");
  assert.equal(transientStatusLabel("importing"), "Importing tasks");
  assert.equal(transientStatusLabel("exporting"), "Exporting tasks");
  assert.equal(transientStatusLabel("conflict"), "Task transfer conflict");
  assert.equal(transientStatusLabel("issue"), "Task transfer issue");
});

test("result copy distinguishes success no-op opposite direction conflict and issue", () => {
  assert.equal(
    formatTransferResult("import", result({ pulled: 1, selected: 1 })).message,
    "Imported 1 task. Reload VS Code or restart the Codex app to see it.",
  );
  assert.equal(
    formatTransferResult("import", result({ selected: 2, unchanged: 2 })).message,
    "No changes were needed. All 2 selected tasks are up to date.",
  );
  assert.equal(
    formatTransferResult("export", result({ selected: 1, issues: [issue("push_requires_pull")] })).message,
    "Export was blocked because 1 selected task is newer in the transfer folder. Import it first.",
  );
  assert.match(
    formatTransferResult("import", result({ outcome: "conflict", conflicts: 1 })).message,
    /no tasks were copied/i,
  );
  const technicalIssue = formatTransferResult(
    "import",
    result({ issues: [issue("unsafe_remote_layout", "do not show this stack detail")] }),
  );
  assert.match(technicalIssue.message, /no tasks were copied/i);
  assert.doesNotMatch(technicalIssue.message, /stack detail/i);
});

test("result copy pluralizes import export no-op and blocked direction exactly", () => {
  assert.equal(
    formatTransferResult("import", result({ pulled: 2, selected: 2 })).message,
    "Imported 2 tasks. Reload VS Code or restart the Codex app to see them.",
  );
  assert.equal(
    formatTransferResult("export", result({ pushed: 1, selected: 1 })).message,
    "Exported 1 task to the transfer folder.",
  );
  assert.equal(
    formatTransferResult("export", result({ pushed: 2, selected: 2 })).message,
    "Exported 2 tasks to the transfer folder.",
  );
  assert.equal(
    formatTransferResult("export", result({ selected: 1, unchanged: 1 })).message,
    "No changes were needed. The selected task is up to date.",
  );
  assert.equal(
    formatTransferResult("import", result({
      selected: 2,
      issues: [issue("pull_requires_push"), issue("pull_requires_push")],
    })).message,
    "Import was blocked because 2 selected tasks are newer on this computer. Export them first.",
  );
});
