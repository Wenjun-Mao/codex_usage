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

test("an active transfer owns orchestration and transient status across every command path", async () => {
  const remoteInventory = inventory([project({ candidateRoots: ["/repo"] })]);
  const localInventory = inventory([project({
    tasks: [task("local-task", "local")],
  })]);
  const port = fakePort({
    folder: "/transfer",
    inventoryQueue: [remoteInventory, localInventory, remoteInventory],
    selectedThreadIdsQueue: [["remote-task"], ["local-task"], ["remote-task"]],
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

  assert.deepEqual(port.statuses, ["checking", undefined]);
  assert.deepEqual(port.notifications.at(-1), [
    "info",
    "Imported 1 task. Reload VS Code or restart the Codex app to see it.",
  ]);
});

test("an active review blocks transfers without clearing its transient status", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([project({ candidateRoots: ["/repo"] })]),
    selectedThreadIds: ["remote-task"],
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
