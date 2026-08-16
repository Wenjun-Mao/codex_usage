const assert = require("node:assert/strict");
const test = require("node:test");

const { TaskTransferController } = require("../out/taskTransfer");
const { taskInventoryWarningMessage } = require("../out/transferPresentation");
const {
  fakePort,
  inventory,
  project,
  transferSelection,
} = require("./taskTransferFixtures");

const inventoryIssue = {
  code: "unidentified_remote_task",
  message: "technical path detail",
  threadId: "",
};

const secondInventoryIssue = {
  code: "unreadable_session",
  message: "second technical detail",
  threadId: "task-2",
};

const expectedLog = [
  "[sync inventory:unidentified_remote_task] technical path detail",
  "[sync inventory:unreadable_session] second technical detail (task-2)",
];

test("inventory diagnostics show one concise warning and log every issue", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory(
      [project({ candidateRoots: ["/repo"] })],
      [inventoryIssue, secondInventoryIssue],
    ),
    selection: transferSelection(["remote-task"]),
  });

  await new TaskTransferController(port).importTasks();

  assert.deepEqual(port.logs, expectedLog);
  assert.deepEqual(port.notifications, [[
    "warning",
    taskInventoryWarningMessage(),
  ], [
    "info",
      "Imported 1 task into Repo. Reload VS Code to display it.",
  ]]);
});

test("inventory warning appears before the empty-source outcome", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([], [inventoryIssue, secondInventoryIssue]),
  });

  await new TaskTransferController(port).importTasks();

  assert.deepEqual(port.logs, expectedLog);
  assert.deepEqual(port.notifications, [[
    "warning",
    taskInventoryWarningMessage(),
  ], [
    "info",
    "No tasks are available to import from this transfer folder.",
  ]]);
});

test("task cancellation adds no notification beyond the inventory warning", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory(
      [project({ candidateRoots: ["/repo"] })],
      [inventoryIssue, secondInventoryIssue],
    ),
    selection: undefined,
  });

  await new TaskTransferController(port).importTasks();

  assert.deepEqual(port.logs, expectedLog);
  assert.deepEqual(port.notifications, [["warning", taskInventoryWarningMessage()]]);
  assert.deepEqual(port.executions, []);
  assert.deepEqual(port.statuses, []);
});
