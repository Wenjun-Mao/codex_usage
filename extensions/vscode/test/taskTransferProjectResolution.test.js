const assert = require("node:assert/strict");
const test = require("node:test");

const { TaskTransferController } = require("../out/taskTransfer");
const {
  fakePort,
  inventory,
  project,
  task,
  transferSelection,
} = require("./taskTransferFixtures");

test("non-git mapping requires confirmation and cancellation aborts the whole import", async () => {
  const remoteProject = project({
    projectKey: "path:/source/project",
    identityKind: "path",
    tasks: [task("task-1"), task("task-2")],
  });
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([remoteProject]),
    selection: transferSelection(
      ["task-1", "task-2"],
      "path:/source/project",
    ),
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
    selection: transferSelection(["remote-task"]),
  });

  await new TaskTransferController(port, () => false).importTasks();

  assert.deepEqual(port.projectRootPrompts, []);
  assert.deepEqual(port.executions[0].request, {
    syncDir: "/transfer",
    projectKey: "git:https://example.com/repo.git",
    projectLabel: "Repo",
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
    selection: transferSelection(["remote-task"]),
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

test("destination mappings are prompted again and never retained across imports", async () => {
  const remote = inventory([project()]);
  const port = fakePort({
    folder: "/transfer",
    inventoryQueue: [remote, remote],
    selectionQueue: [
      transferSelection(["remote-task"]),
      transferSelection(["remote-task"]),
    ],
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
