const assert = require("node:assert/strict");
const test = require("node:test");

const { TaskTransferController } = require("../out/taskTransfer");
const { fakePort, inventory, project } = require("./taskTransferFixtures");

const inventoryIssue = {
  code: "unidentified_remote_task",
  message: "technical path detail",
  threadId: "",
};

const expectedLog = [
  "[sync inventory:unidentified_remote_task] technical path detail",
];

test("inventory diagnostics stay log-only when import succeeds", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory(
      [project({ candidateRoots: ["/repo"] })],
      [inventoryIssue],
    ),
    selectedThreadIds: ["remote-task"],
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.logs, expectedLog);
  assert.deepEqual(port.notifications, [[
    "info",
    "Imported 1 task. Reload VS Code or restart the Codex app to see it.",
  ]]);
});

test("inventory diagnostics stay log-only before the empty-source outcome", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory([], [inventoryIssue]),
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.logs, expectedLog);
  assert.deepEqual(port.notifications, [[
    "info",
    "No tasks are available to import from this transfer folder.",
  ]]);
});

test("cancellation stays silent when inventory diagnostics were logged", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventory(
      [project({ candidateRoots: ["/repo"] })],
      [inventoryIssue],
    ),
    selectedThreadIds: undefined,
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.logs, expectedLog);
  assert.deepEqual(port.notifications, []);
  assert.deepEqual(port.executions, []);
  assert.deepEqual(port.statuses, ["checking", undefined]);
});
