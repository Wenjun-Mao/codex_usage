const assert = require("node:assert/strict");
const test = require("node:test");

const {
  TaskTransferController,
} = require("../out/taskTransfer");
const {
  certifiedImportThreadIds,
} = require("../out/taskTransferRegistration");
const {
  completed,
  fakePort,
  inventory,
  issueResult,
  project,
  statusSummary,
  task,
  transferSelection,
} = require("./taskTransferFixtures");

test("certifies completed, partial, conflict, and blocked imports", () => {
  const completedImport = completed("import", ["task-a"]);
  completedImport.counts.selected = 2;
  completedImport.counts.unchanged = 1;

  const partialImportWithPulledA = completed("import", ["task-a"]);
  partialImportWithPulledA.outcome = "issue";
  partialImportWithPulledA.counts.selected = 2;
  partialImportWithPulledA.counts.issues = 1;
  partialImportWithPulledA.issues = [{
    code: "transfer_filesystem_failure",
    message: "copy stopped",
    thread_id: "task-b",
  }];

  const conflictResult = completed("import", []);
  conflictResult.outcome = "conflict";
  conflictResult.counts.conflicts = 1;

  const blockedIssueResult = issueResult(
    "pull_requires_push",
    "The local task is newer.",
  );

  assert.deepEqual(
    certifiedImportThreadIds(completedImport, ["task-a", "task-b"]),
    ["task-a", "task-b"],
  );
  assert.deepEqual(
    certifiedImportThreadIds(partialImportWithPulledA, ["task-a", "task-b"]),
    ["task-a"],
  );
  assert.deepEqual(certifiedImportThreadIds(conflictResult, ["task-a"]), []);
  assert.deepEqual(certifiedImportThreadIds(blockedIssueResult, ["task-a"]), []);
});

test("completed imports register every selected id after transfer, including unchanged", async () => {
  const executionResult = completed("import", ["task-a"]);
  executionResult.counts.selected = 2;
  executionResult.counts.unchanged = 1;
  const port = importPort(["task-a", "task-b"], executionResult);

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.registrationCalls, [["task-a", "task-b"]]);
  assert.equal(port.executions.length, 1);
});

test("partial imports register only certified pulled ids", async () => {
  const executionResult = completed("import", ["task-a"]);
  executionResult.outcome = "issue";
  executionResult.counts.selected = 2;
  executionResult.counts.issues = 1;
  executionResult.issues = [{
    code: "transfer_filesystem_failure",
    message: "copy stopped",
    thread_id: "task-b",
  }];
  const port = importPort(["task-a", "task-b"], executionResult);

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.registrationCalls, [["task-a"]]);
});

test("export, review, conflict, and pre-copy issues never register", async () => {
  const conflict = completed("import", []);
  conflict.outcome = "conflict";
  conflict.counts.conflicts = 1;
  const cases = [
    {
      method: "exportTasks",
      port: fakePort({
        folder: "/transfer",
        inventory: inventory([project({ tasks: [task("task-a", "local")] })]),
        selection: transferSelection(["task-a"]),
      }),
    },
    {
      method: "reviewStatus",
      port: fakePort({
        folder: "/transfer",
        inventory: inventory([project()]),
        selection: transferSelection(["remote-task"]),
        reviewResult: statusSummary({ total: 1 }),
      }),
    },
    { method: "importTasks", port: importPort(["task-a"], conflict) },
    {
      method: "importTasks",
      port: importPort(
        ["task-a"],
        issueResult("pull_requires_push", "The local task is newer."),
      ),
    },
  ];

  for (const entry of cases) {
    await new TaskTransferController(entry.port, () => true)[entry.method]();
    assert.deepEqual(entry.port.registrationCalls, [], entry.method);
  }
});

test("registration is awaited, reported separately, and preserves single-flight cleanup", async () => {
  let releaseRegistration;
  const registrationPending = new Promise((resolve) => {
    releaseRegistration = resolve;
  });
  const executionResult = completed("import", ["task-a", "task-b", "task-c"]);
  const originalResult = structuredClone(executionResult);
  const port = importPort(["task-a", "task-b", "task-c"], executionResult, {
    registrationResult: registrationPending,
    executionStatus: "importing",
  });

  const controller = new TaskTransferController(port, () => true);
  const importPending = controller.importTasks();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(port.registrationCalls, [["task-a", "task-b", "task-c"]]);
  assert.deepEqual(port.notifications, []);
  assert.deepEqual(port.statuses, ["checking", "importing", "registering"]);

  await controller.exportTasks();
  assert.match(port.notifications[0][1], /already running/);

  releaseRegistration({
    attemptedThreadIds: ["task-a", "task-b", "task-c"],
    registeredThreadIds: ["task-a"],
    failures: [
      {
        threadId: "task-b",
        message: "ROLLOUT-CONTENT at /private/codex/state",
      },
      {
        threadId: "task-c",
        message: "RPC failed at /Users/example/.codex/private-state",
      },
    ],
  });
  await importPending;

  assert.equal(port.executions.length, 1);
  assert.deepEqual(executionResult, originalResult);
  assert.deepEqual(port.statuses, [
    "checking", "importing", "registering", undefined,
  ]);
  assert.deepEqual(port.logs, [
    "[task registration] task-b: Codex registration could not be completed",
    "[task registration] task-c: Codex registration could not be completed",
  ]);
  assert.doesNotMatch(
    port.logs.join("\n"),
    /ROLLOUT-CONTENT|\/private\/codex\/state|\/Users\/example\/\.codex/i,
  );
  assert.doesNotMatch(port.notifications[1][1], /Task completion could not be determined/);
});

test("unexpected registrar rejection stays a registration failure", async () => {
  const port = importPort(
    ["task-a", "task-b"],
    completed("import", ["task-a", "task-b"]),
    { registrationError: new Error("private discovery path") },
  );

  await new TaskTransferController(port, () => true).importTasks();

  assert.equal(port.executions.length, 1);
  assert.deepEqual(port.registrationCalls, [["task-a", "task-b"]]);
  assert.equal(port.notifications[0][0], "warning");
  assert.match(port.notifications[0][1], /files are safe/i);
  assert.doesNotMatch(port.notifications[0][1], /completion could not be determined/i);
  assert.deepEqual(port.logs, [
    "[task registration] task-a: Codex registration could not be completed",
    "[task registration] task-b: Codex registration could not be completed",
  ]);
  assert.doesNotMatch(port.logs.join("\n"), /private discovery path/);
  assert.deepEqual(port.statuses, ["checking", "registering", undefined]);
});

function importPort(threadIds, executionResult, overrides = {}) {
  return fakePort({
    folder: "/transfer",
    inventory: inventory([project({
      projectLabel: "Letta-Open-ADE",
      candidateRoots: ["/repo"],
      tasks: threadIds.map((threadId) => task(threadId)),
    })]),
    selection: transferSelection(threadIds),
    executionResult,
    ...overrides,
  });
}
