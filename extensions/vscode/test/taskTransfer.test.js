const assert = require("node:assert/strict");
const test = require("node:test");

const {
  TaskTransferController,
  TransferFolderUnavailableError,
} = require("../out/taskTransfer");
const {
  fakePort,
  inventory,
  issueResult,
  project,
  statusSummary,
  task,
} = require("./taskTransferFixtures");

test("import lazily chooses and remembers a transfer folder", async () => {
  const port = fakePort({
    chosenTransferFolder: "/transfer",
    inventory: inventory([project({ candidateRoots: ["/workspace"] })]),
    selectedThreadIds: ["remote-task"],
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.folderWrites, ["/transfer"]);
  assert.deepEqual(port.inventoryRequests, [{
    syncDir: "/transfer",
    autoTransitions: true,
    candidateProjectRoots: ["/workspace"],
  }]);
  assert.deepEqual(port.notifications, [[
    "info",
    "Imported 1 task. Reload VS Code or restart the Codex app to see it.",
  ]]);
  assert.deepEqual(port.statuses, ["checking", undefined]);
});

test("cancelling lazy folder choice is silent", async () => {
  const port = fakePort({ chosenTransferFolder: undefined });

  await new TaskTransferController(port, () => true).exportTasks();

  assert.deepEqual(port.notifications, []);
  assert.deepEqual(port.inventoryRequests, []);
  assert.deepEqual(port.executions, []);
  assert.deepEqual(port.statuses, []);
});

test("empty import and export sources get state-specific messages", async () => {
  const importPort = fakePort({ folder: "/transfer", inventory: inventory() });
  const exportPort = fakePort({ folder: "/transfer", inventory: inventory() });

  await new TaskTransferController(importPort, () => true).importTasks();
  await new TaskTransferController(exportPort, () => true).exportTasks();

  assert.deepEqual(importPort.notifications, [[
    "info", "No tasks are available to import from this transfer folder.",
  ]]);
  assert.deepEqual(exportPort.notifications, [[
    "info", "No active Codex tasks are available to export from this computer.",
  ]]);
  assert.deepEqual(importPort.statuses, ["checking", undefined]);
  assert.deepEqual(exportPort.statuses, ["checking", undefined]);
});

test("inventory issues are logged and summarized without exposing technical detail", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory(
      [project({ candidateRoots: ["/repo"] })],
      [{ code: "unidentified_remote_task", message: "technical path detail", threadId: "" }],
    ),
    selectedThreadIds: undefined,
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.logs, [
    "[sync inventory:unidentified_remote_task] technical path detail",
  ]);
  assert.deepEqual(port.notifications, [[
    "warning",
    "Some tasks in the transfer folder could not be identified and were omitted. See Codex Usage output for details.",
  ]]);
});

test("each operation opens an empty fresh selection and never writes task ids", async () => {
  const remote = inventory([project()]);
  const port = fakePort({
    folder: "/transfer",
    inventoryQueue: [remote, remote],
    selectedThreadIdsQueue: [["remote-task"], undefined],
  });
  const controller = new TaskTransferController(port, () => true);

  await controller.importTasks();
  await controller.importTasks();

  assert.deepEqual(port.selectionCalls.map((call) => call.initialThreadIds), [[], []]);
  assert.deepEqual(port.folderWrites, []);
  assert.equal("threadIdWrites" in port, false);
});

test("change open and forget affect only the remembered folder", async () => {
  const port = fakePort({
    folder: "/old-transfer",
    chosenTransferFolder: "/new-transfer",
  });
  const controller = new TaskTransferController(port, () => true);

  await controller.changeFolder();
  await controller.openFolder();
  await controller.forgetFolder();

  assert.deepEqual(port.folderWrites, ["/new-transfer", undefined]);
  assert.deepEqual(port.openedFolders, ["/new-transfer"]);
  assert.equal("deletedPaths" in port, false);
});

test("ambiguous destination choice becomes one binding for all selected project tasks", async () => {
  const remoteProject = project({
    candidateRoots: ["/repo-a", "/repo-b"],
    tasks: [task("task-1"), task("task-2")],
  });
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([remoteProject]),
    selectedThreadIds: ["task-1", "task-2"],
    chosenProjectRoot: "/repo-b",
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.equal(port.projectRootPrompts.length, 1);
  assert.deepEqual(port.executions[0].request.projectBindings, [{
    projectKey: remoteProject.projectKey,
    path: "/repo-b",
    confirmedUnverified: false,
  }]);
});

test("non-git mapping requires confirmation and cancellation aborts the whole import", async () => {
  const remoteProject = project({
    projectKey: "path:/source/project",
    identityKind: "path",
    tasks: [task("task-1"), task("task-2")],
  });
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([remoteProject]),
    selectedThreadIds: ["task-1", "task-2"],
    chosenProjectRoot: "/local/project",
    confirmUnverified: false,
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.equal(port.confirmationPrompts.length, 1);
  assert.deepEqual(port.executions, []);
  assert.deepEqual(port.notifications, []);
  assert.deepEqual(port.statuses, ["checking", undefined]);
});

test("a unique destination candidate resolves without prompting", async () => {
  const port = fakePort({
    folder: "/transfer",
    workspaceRoots: ["/workspace", "/repo"],
    inventory: inventory([project({ candidateRoots: ["/repo"] })]),
    selectedThreadIds: ["remote-task"],
  });

  await new TaskTransferController(port, () => false).importTasks();

  assert.deepEqual(port.projectRootPrompts, []);
  assert.deepEqual(port.executions[0].request, {
    syncDir: "/transfer",
    threadIds: ["remote-task"],
    autoTransitions: false,
    candidateProjectRoots: ["/workspace", "/repo"],
    projectBindings: [{
      projectKey: "git:https://example.com/repo.git",
      path: "/repo",
      confirmedUnverified: false,
    }],
  });
});

test("a missing destination candidate falls back to one current-operation binding", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([project()]),
    selectedThreadIds: ["remote-task"],
    chosenProjectRoot: "/chosen/repo",
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.projectRootPrompts[0].candidates, []);
  assert.deepEqual(port.executions[0].request.projectBindings, [{
    projectKey: "git:https://example.com/repo.git",
    path: "/chosen/repo",
    confirmedUnverified: false,
  }]);
});

test("engine destination issues stay technical while the notification stays concise", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([project({ candidateRoots: ["/repo"] })]),
    selectedThreadIds: ["remote-task"],
    executionResult: issueResult(
      "project_binding_identity_mismatch",
      "Expected git:example/repo but found git:other/repo.",
    ),
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.match(port.logs[0], /project_binding_identity_mismatch/);
  assert.match(port.logs[0], /Expected git:example\/repo/);
  assert.deepEqual(port.notifications, [[
    "error",
    "Import could not be completed. No tasks were copied. See the Codex Usage output for details.",
  ]]);
  assert.deepEqual(port.statuses, ["checking", "issue", undefined]);
});

test("destination mappings are prompted again and never retained across imports", async () => {
  const remote = inventory([project()]);
  const port = fakePort({
    folder: "/transfer",
    inventoryQueue: [remote, remote],
    selectedThreadIdsQueue: [["remote-task"], ["remote-task"]],
    chosenProjectRootQueue: ["/first", "/second"],
  });
  const controller = new TaskTransferController(port, () => true);

  await controller.importTasks();
  await controller.importTasks();

  assert.equal(port.projectRootPrompts.length, 2);
  assert.deepEqual(
    port.executions.map((call) => call.request.projectBindings[0].path),
    ["/first", "/second"],
  );
});

test("local counterparts and Review never prompt for destination bindings", async () => {
  const bothProject = project({ tasks: [task("both-task", "both")] });
  const importPort = fakePort({
    folder: "/transfer",
    inventory: inventory([bothProject]),
    selectedThreadIds: ["both-task"],
  });
  const reviewPort = fakePort({
    folder: "/transfer",
    inventory: inventory([project({ candidateRoots: ["/desktop-root"] })]),
    selectedThreadIds: ["remote-task"],
    reviewResult: statusSummary({
      total: 3,
      synced: 1,
      localChanges: 1,
      remoteChanges: 1,
    }),
  });

  await new TaskTransferController(importPort, () => true).importTasks();
  await new TaskTransferController(reviewPort, () => true).reviewStatus();

  assert.deepEqual(importPort.projectRootPrompts, []);
  assert.deepEqual(importPort.executions[0].request.projectBindings, []);
  assert.deepEqual(reviewPort.projectRootPrompts, []);
  assert.deepEqual(reviewPort.reviews[0].projectBindings, []);
  assert.deepEqual(reviewPort.reviews[0].candidateProjectRoots, [
    "/workspace", "/desktop-root",
  ]);
  assert.deepEqual(reviewPort.notifications, [[
    "info",
    "Task Transfer status: 3 tasks, 1 up to date, 1 newer on this computer, 1 newer in the transfer folder.",
  ]]);
  assert.doesNotMatch(reviewPort.notifications[0][1], /sync|local|remote/i);
});

test("task and destination picker cancellations stay silent", async () => {
  const taskPort = fakePort({
    folder: "/transfer",
    inventory: inventory([project()]),
    selectedThreadIds: undefined,
  });
  const projectPort = fakePort({
    folder: "/transfer",
    inventory: inventory([project()]),
    selectedThreadIds: ["remote-task"],
    chosenProjectRoot: undefined,
  });

  await new TaskTransferController(taskPort, () => true).importTasks();
  await new TaskTransferController(projectPort, () => true).importTasks();

  assert.deepEqual(taskPort.notifications, []);
  assert.deepEqual(projectPort.notifications, []);
  assert.deepEqual(taskPort.executions, []);
  assert.deepEqual(projectPort.executions, []);
});

test("remembered unavailable folders get an actionable error and are not rewritten", async () => {
  const port = fakePort({
    folder: "/offline-transfer",
    inventoryError: new TransferFolderUnavailableError("/offline-transfer"),
  });

  await new TaskTransferController(port, () => true).exportTasks();

  assert.deepEqual(port.folderWrites, []);
  assert.deepEqual(port.executions, []);
  assert.deepEqual(port.notifications, [[
    "error",
    "The transfer folder is not available: /offline-transfer. Choose another transfer folder and try again.",
  ]]);
  assert.deepEqual(port.statuses, ["checking", undefined]);
});

test("opening an unavailable remembered folder reports the same error without status leakage", async () => {
  const port = fakePort({
    folder: "/offline-transfer",
    openFolderError: new TransferFolderUnavailableError("/offline-transfer"),
  });

  await new TaskTransferController(port, () => true).openFolder();

  assert.deepEqual(port.folderWrites, []);
  assert.deepEqual(port.openedFolders, []);
  assert.deepEqual(port.statuses, []);
  assert.deepEqual(port.notifications, [[
    "error",
    "The transfer folder is not available: /offline-transfer. Choose another transfer folder and try again.",
  ]]);
});

test("unexpected failures are logged and always clear transient transfer status", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([project({ candidateRoots: ["/repo"] })]),
    selectedThreadIds: ["remote-task"],
    executionError: new Error("process failed"),
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.logs, ["[error] process failed"]);
  assert.deepEqual(port.statuses, ["checking", "issue", undefined]);
  assert.deepEqual(port.notifications, [[
    "error",
    "Import could not be completed. No tasks were copied. See the Codex Usage output for details.",
  ]]);
});

test("export execution failures keep export-specific notification copy", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([project({ tasks: [task("local-task", "local")] })]),
    selectedThreadIds: ["local-task"],
    executionError: new Error("process failed"),
  });

  await new TaskTransferController(port, () => true).exportTasks();

  assert.deepEqual(port.notifications, [[
    "error",
    "Export could not be completed. No tasks were copied. See the Codex Usage output for details.",
  ]]);
  assert.deepEqual(port.statuses, ["checking", "issue", undefined]);
});

test("menu actions delegate through one controller and folder-only state", async () => {
  const port = fakePort({ folder: "/transfer", menuAction: "forgetFolder" });

  await new TaskTransferController(port, () => true).showMenu();

  assert.deepEqual(port.folderWrites, [undefined]);
  assert.deepEqual(port.menuItems[0].map((item) => item.action), [
    "importTasks", "exportTasks", "reviewStatus", "changeFolder", "openFolder", "forgetFolder",
  ]);
});
