const assert = require("node:assert/strict");
const test = require("node:test");

const {
  formatTransferResult,
  taskAvailabilityLabel,
  taskInventoryWarningMessage,
  taskPickerDetail,
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

const PROJECT = "Letta-Open-ADE";

function registration(attempted, registered = attempted) {
  return {
    attemptedThreadIds: Array.from(
      { length: attempted },
      (_, index) => `task-${index + 1}`,
    ),
    registeredThreadIds: Array.from(
      { length: registered },
      (_, index) => `task-${index + 1}`,
    ),
    failures: Array.from(
      { length: attempted - registered },
      (_, index) => ({
        threadId: `task-${registered + index + 1}`,
        message: "Codex unavailable",
      }),
    ),
  };
}

function format(operation, syncResult, registrationResult) {
  return formatTransferResult(operation, syncResult, {
    projectLabel: PROJECT,
    registration: registrationResult,
  });
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

test("picker details and inventory warnings use Task Transfer vocabulary", () => {
  assert.equal(
    taskPickerDetail("thread-1", "1.5 KB"),
    "Task ID: thread-1 | Estimated task transfer size: 1.5 KB",
  );
  assert.equal(taskPickerDetail("missing-thread"), "Task ID: missing-thread");
  assert.equal(
    taskInventoryWarningMessage(),
    "Some tasks in the transfer folder could not be identified and were omitted. See Codex Usage output for details.",
  );

  const copy = JSON.stringify({
    detail: taskPickerDetail("thread-1", "1.5 KB"),
    warning: taskInventoryWarningMessage(),
  });
  assert.doesNotMatch(copy, /This device|Sync folder|Thread ID|estimated sync size|remote task files/i);
});

test("transient states use usage-status Task Transfer wording", () => {
  assert.equal(transientStatusLabel("checking"), "Checking tasks");
  assert.equal(transientStatusLabel("importing"), "Importing tasks");
  assert.equal(transientStatusLabel("exporting"), "Exporting tasks");
  assert.equal(transientStatusLabel("registering"), "Registering imported tasks");
  assert.equal(transientStatusLabel("conflict"), "Task transfer conflict");
  assert.equal(transientStatusLabel("issue"), "Task transfer issue");
});

test("result copy distinguishes success no-op opposite direction conflict and issue", () => {
  assert.equal(
    format("import", result({ pulled: 1, selected: 1 }), registration(1)).message,
    "Imported 1 task into Letta-Open-ADE. Open or restart Codex to display it.",
  );
  assert.equal(
    format("import", result({ selected: 2, unchanged: 2 }), registration(2)).message,
    "No file changes were needed for 2 tasks in Letta-Open-ADE. " +
      "Registered them with Codex. Open or restart Codex to display them.",
  );
  assert.equal(
    format("export", result({ selected: 1, issues: [issue("push_requires_pull")] })).message,
    "Export from Letta-Open-ADE was blocked because 1 selected task is newer " +
      "in the transfer folder. Import it first.",
  );
  assert.match(
    format("import", result({ outcome: "conflict", conflicts: 1 })).message,
    /Import into Letta-Open-ADE was blocked by 1 conflict.*no tasks were copied/i,
  );
  const technicalIssue = format(
    "import",
    result({ issues: [issue("unsafe_remote_layout", "do not show this stack detail")] }),
  );
  assert.match(technicalIssue.message, /no tasks were copied/i);
  assert.doesNotMatch(technicalIssue.message, /stack detail/i);
});

test("result copy pluralizes import export no-op and blocked direction exactly", () => {
  assert.equal(
    format("import", result({ pulled: 2, selected: 2 }), registration(2)).message,
    "Imported 2 tasks into Letta-Open-ADE. Open or restart Codex to display them.",
  );
  assert.equal(
    format("export", result({ pushed: 1, selected: 1 })).message,
    "Exported 1 task from Letta-Open-ADE to the transfer folder.",
  );
  assert.equal(
    format("export", result({ pushed: 2, selected: 2 })).message,
    "Exported 2 tasks from Letta-Open-ADE to the transfer folder.",
  );
  assert.equal(
    format("export", result({ selected: 1, unchanged: 1 })).message,
    "No file changes were needed for 1 task in Letta-Open-ADE. It is up to date.",
  );
  assert.equal(
    format("import", result({
      selected: 2,
      issues: [issue("pull_requires_push"), issue("pull_requires_push")],
    })).message,
    "Import into Letta-Open-ADE was blocked because 2 selected tasks are newer " +
      "on this computer. Export them first.",
  );
});

test("registration failures report safe partial completion without false success", () => {
  const partial = format(
    "import",
    result({ pulled: 2, selected: 2 }),
    registration(2, 1),
  );
  assert.equal(partial.kind, "warning");
  assert.equal(
    partial.message,
    "Imported files for 2 tasks into Letta-Open-ADE, but Codex registered only 1. " +
      "The files are safe. Retry Import after resolving Codex availability.",
  );

  const zero = format(
    "import",
    result({ pulled: 1, selected: 1 }),
    registration(1, 0),
  );
  assert.equal(zero.kind, "warning");
  assert.equal(
    zero.message,
    "Imported files for 1 task into Letta-Open-ADE, but Codex registered 0 and " +
      "failed to register 1. The file is safe. Retry Import after resolving " +
      "Codex availability.",
  );
  assert.doesNotMatch(`${partial.message}\n${zero.message}`, /Imported \d+ tasks? into/);
});

test("singular no-op registration uses singular task and pronouns", () => {
  assert.equal(
    format(
      "import",
      result({ selected: 1, unchanged: 1 }),
      registration(1),
    ).message,
    "No file changes were needed for 1 task in Letta-Open-ADE. Registered it " +
      "with Codex. Open or restart Codex to display it.",
  );
});

test("mixed imported and unchanged outcomes keep counts and grammar accurate", () => {
  const mixedResult = result({
    selected: 2,
    pulled: 1,
    unchanged: 1,
  });
  assert.equal(
    format("import", mixedResult, registration(2)).message,
    "Imported 1 task into Letta-Open-ADE and registered 2 tasks with Codex. " +
      "Open or restart Codex to display them.",
  );
  assert.equal(
    format("import", mixedResult, registration(2, 1)).message,
    "Imported files for 1 task into Letta-Open-ADE; 1 task was already current, " +
      "but Codex registered only 1. The files are safe. Retry Import after " +
      "resolving Codex availability.",
  );
});

test("runtime import failure reports the task imported before the issue", () => {
  const formatted = format(
    "import",
    result({
      selected: 2,
      pulled: 1,
      issues: [issue("transfer_filesystem_failure")],
    }),
    registration(1),
  );

  assert.equal(formatted.kind, "error");
  assert.equal(
    formatted.message,
    "Import into Letta-Open-ADE could not be completed. Imported files for 1 task " +
      "before the issue occurred. Registered it with Codex. " +
      "Open or restart Codex to display it. " +
      "See the Codex Usage output for details.",
  );
  assert.doesNotMatch(formatted.message, /no tasks were copied/i);
});

test("runtime export failure reports the task exported before the issue", () => {
  const formatted = format(
    "export",
    result({
      selected: 2,
      pushed: 1,
      issues: [issue("transfer_filesystem_failure")],
    }),
  );

  assert.equal(formatted.kind, "error");
  assert.equal(
    formatted.message,
    "Export from Letta-Open-ADE could not be completed. Exported 1 task to the " +
      "transfer folder before the issue occurred. " +
      "See the Codex Usage output for details.",
  );
  assert.doesNotMatch(formatted.message, /no tasks were copied/i);
});

test("filesystem failure without certified ids reports unknown completion", () => {
  for (const operation of ["import", "export"]) {
    const formatted = format(
      operation,
      result({
        selected: 1,
        issues: [issue("transfer_filesystem_failure")],
      }),
    );

    assert.match(formatted.message, /Task completion could not be determined/);
    assert.doesNotMatch(formatted.message, /No tasks were copied/i);
  }
});
