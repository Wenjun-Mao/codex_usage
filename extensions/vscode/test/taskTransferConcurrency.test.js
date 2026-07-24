const assert = require("node:assert/strict");
const test = require("node:test");

const { TaskTransferController } = require("../out/taskTransfer");
const {
  completed,
  fakePort,
  inventory,
  project,
  statusSummary,
  task,
  transferSelection,
} = require("./taskTransferFixtures");

const busyNotification = [
  "info",
  "A Task Transfer operation is already running. Try again when it finishes.",
];

function deferred() {
  let resolve;
  const promise = new Promise((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

const pendingCommandCases = [
  { label: "Show menu", command: "showMenu", portMethod: "chooseMenu" },
  { label: "Choose folder", command: "chooseFolder", portMethod: "chooseTransferFolder" },
  { label: "Change folder", command: "changeFolder", portMethod: "chooseTransferFolder" },
  { label: "Open folder", command: "openFolder", portMethod: "openFolder" },
  { label: "Forget folder", command: "forgetFolder", portMethod: "writeFolder" },
];

const competingOperationCases = [
  { label: "Import", run: (controller) => controller.importTasks() },
  { label: "Export", run: (controller) => controller.exportTasks() },
  { label: "Review", run: (controller) => controller.reviewStatus() },
];

function holdPortCall(port, methodName, entered, release) {
  const original = port[methodName].bind(port);
  port[methodName] = async (...args) => {
    entered.resolve();
    await release.promise;
    return original(...args);
  };
}

for (const pendingCommand of pendingCommandCases) {
  for (const operation of competingOperationCases) {
    test(`${pendingCommand.label} owns the lease before ${operation.label}`, async () => {
      const port = fakePort({
        folder: "/transfer",
        inventory: inventory([project({
          candidateRoots: ["/repo"],
          tasks: [task("remote-task"), task("local-task", "local")],
        })]),
        selection: transferSelection(["remote-task", "local-task"]),
      });
      const commandEntered = deferred();
      const commandRelease = deferred();
      holdPortCall(port, pendingCommand.portMethod, commandEntered, commandRelease);
      const controller = new TaskTransferController(port, () => true);

      const activeCommand = controller[pendingCommand.command]();
      await commandEntered.promise;

      try {
        await operation.run(controller);

        assert.deepEqual(port.inventoryRequests, []);
        assert.deepEqual(port.selectionCalls, []);
        assert.deepEqual(port.executions, []);
        assert.deepEqual(port.reviews, []);
        assert.deepEqual(port.folderWrites, []);
        assert.deepEqual(port.statuses, []);
        assert.deepEqual(port.notifications, [busyNotification]);
      } finally {
        commandRelease.resolve();
        await activeCommand;
      }

      assert.deepEqual(port.notifications, [busyNotification]);
    });
  }
}

test("an active transfer owns orchestration and transient status across every command path", async () => {
  const remoteInventory = inventory([project({ candidateRoots: ["/repo"] })]);
  const localInventory = inventory([project({
    tasks: [task("local-task", "local")],
  })]);
  const port = fakePort({
    folder: "/transfer",
    inventoryQueue: [remoteInventory, localInventory, remoteInventory],
    selectionQueue: [
      transferSelection(["remote-task"]),
      transferSelection(["local-task"]),
      { threadIds: ["remote-task"] },
    ],
    chosenTransferFolderQueue: ["/chosen", "/changed"],
  });
  const operationStarted = deferred();
  const operationDone = deferred();
  let executionCount = 0;
  port.execute = async function execute(operation, request) {
    this.executions.push({ operation, request });
    executionCount += 1;
    if (executionCount === 1) {
      operationStarted.resolve();
      return operationDone.promise;
    }
    return completed(operation, request.threadIds);
  };
  const controller = new TaskTransferController(port, () => true);

  const activeImport = controller.importTasks();
  await operationStarted.promise;

  try {
    await controller.exportTasks();
    await controller.reviewStatus();
    await controller.chooseFolder();
    await controller.changeFolder();
    await controller.openFolder();
    await controller.forgetFolder();
    await controller.showMenu();

    assert.equal(port.inventoryRequests.length, 1);
    assert.equal(port.executions.length, 1);
    assert.equal(port.reviews.length, 0);
    assert.deepEqual(port.folderWrites, []);
    assert.deepEqual(port.openedFolders, []);
    assert.deepEqual(port.menuItems, []);
    assert.deepEqual(port.statuses, ["checking"]);
    assert.deepEqual(port.notifications, Array(7).fill(busyNotification));
  } finally {
    operationDone.resolve(completed("import", ["remote-task"]));
    await activeImport;
  }

  assert.deepEqual(port.statuses, ["checking", "registering", undefined]);
  assert.deepEqual(port.notifications.at(-1), [
    "info",
    "Imported 1 task into Repo. Open or restart Codex to display it.",
  ]);
});

test("an active review blocks transfers without clearing its transient status", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([project({ candidateRoots: ["/repo"] })]),
    selection: { threadIds: ["remote-task"] },
  });
  const reviewStarted = deferred();
  const reviewDone = deferred();
  port.review = async function review(request) {
    this.reviews.push(request);
    reviewStarted.resolve();
    return reviewDone.promise;
  };
  const controller = new TaskTransferController(port, () => true);

  const activeReview = controller.reviewStatus();
  await reviewStarted.promise;

  try {
    await controller.importTasks();
    await controller.exportTasks();

    assert.equal(port.inventoryRequests.length, 1);
    assert.equal(port.reviews.length, 1);
    assert.deepEqual(port.executions, []);
    assert.deepEqual(port.statuses, ["checking"]);
    assert.deepEqual(port.notifications, [busyNotification, busyNotification]);
  } finally {
    reviewDone.resolve(statusSummary({ total: 1, synced: 1 }));
    await activeReview;
  }

  assert.deepEqual(port.statuses, ["checking", undefined]);
});
