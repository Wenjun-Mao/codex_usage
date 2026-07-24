const assert = require("node:assert/strict");
const test = require("node:test");

const {
  chooseFreshTaskTransferSelection,
  selectTaskTransferOperation,
} = require("../out/taskTransferOperation");

function selectionPort(selections) {
  const calls = [];
  return {
    calls,
    async loadRows(folder) {
      calls.push(["load", folder]);
      return [{ id: `task:${folder}`, kind: "task" }];
    },
    async chooseTasks(operation, rows) {
      calls.push(["choose", operation, rows.map((row) => row.id)]);
      return selections.shift();
    },
  };
}

test("two consecutive operations each open with no preselection", async () => {
  const port = selectionPort([
    { projectKey: "repo-a", threadIds: ["import-task"] },
    { projectKey: "repo-b", threadIds: ["export-task"] },
  ]);

  assert.deepEqual(await selectTaskTransferOperation("import", "/transfer", port), {
    projectKey: "repo-a", threadIds: ["import-task"],
  });
  assert.deepEqual(await selectTaskTransferOperation("export", "/transfer", port), {
    projectKey: "repo-b", threadIds: ["export-task"],
  });

  assert.deepEqual(port.calls.filter((call) => call[0] === "choose"), [
    ["choose", "import", ["task:/transfer"]],
    ["choose", "export", ["task:/transfer"]],
  ]);
});

test("review cannot reuse a previous import or export selection", async () => {
  const port = selectionPort([
    { projectKey: "repo-a", threadIds: ["import-task"] },
    { projectKey: "repo-b", threadIds: ["export-task"] },
    undefined,
  ]);

  await selectTaskTransferOperation("import", "/transfer", port);
  await selectTaskTransferOperation("export", "/transfer", port);
  assert.equal(await selectTaskTransferOperation("review", "/transfer", port), undefined);

  assert.deepEqual(port.calls.at(-1), ["choose", "review", ["task:/transfer"]]);
});

test("controller-ready rows still cross the shared empty-selection boundary", async () => {
  const port = selectionPort([{ projectKey: "repo-a", threadIds: ["task-1"] }]);
  const rows = [{ id: "task:task-1", kind: "task" }];

  assert.deepEqual(
    await chooseFreshTaskTransferSelection("import", rows, port),
    { projectKey: "repo-a", threadIds: ["task-1"] },
  );
  assert.deepEqual(port.calls, [["choose", "import", ["task:task-1"]]]);
});
