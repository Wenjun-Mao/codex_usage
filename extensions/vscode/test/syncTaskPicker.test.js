const assert = require("node:assert/strict");
const test = require("node:test");

const { filterInventoryForOperation } = require("../out/syncInventory");
const {
  buildTaskPickerItems,
  reduceTaskSelection,
  selectedPickerItemIds,
} = require("../out/syncTaskPicker");

function inventory() {
  return {
    inventoryVersion: 2,
    projects: [
      {
        projectKey: "repo-a",
        projectLabel: "Repo A",
        identityKind: "git",
        candidateRoots: ["D:/Code/repo-a"],
        tasks: [
          {
            threadId: "thread-1",
            title: "Persona - execution",
            updatedAt: "2026-07-14T12:00:00Z",
            estimatedSyncBytes: 1536,
            availability: "local",
            state: "local_only",
            action: "push",
          },
          {
            threadId: "thread-2",
            title: "Planning notes",
            updatedAt: "2026-07-13T12:00:00Z",
            estimatedSyncBytes: 2048,
            availability: "both",
            state: "synced",
            action: "none",
          },
        ],
      },
      {
        projectKey: "repo-b",
        projectLabel: "Repo B",
        identityKind: "path",
        candidateRoots: ["D:/Code/repo-b"],
        tasks: [
          {
            threadId: "thread-3",
            title: "Remote task",
            updatedAt: "2026-07-12T12:00:00Z",
            estimatedSyncBytes: 512,
            availability: "remote",
            state: "remote_only",
            action: "pull",
          },
        ],
      },
    ],
    issues: [],
  };
}

function taskIds(items) {
  return items
    .filter((item) => item.kind === "task")
    .map((item) => item.threadId);
}

test("import lists transfer-folder tasks and starts unselected", () => {
  const items = buildTaskPickerItems(inventory(), "import");

  assert.deepEqual(taskIds(items), ["thread-2", "thread-3"]);
  assert.deepEqual(selectedPickerItemIds(items, []), []);
});

test("export lists active local tasks and review lists the union", () => {
  assert.deepEqual(taskIds(buildTaskPickerItems(inventory(), "export")), [
    "thread-1",
    "thread-2",
  ]);
  assert.deepEqual(taskIds(buildTaskPickerItems(inventory(), "review")), [
    "thread-1",
    "thread-2",
    "thread-3",
  ]);
});

test("operation filtering drops empty projects without mutating the inventory", () => {
  const source = inventory();
  const filtered = filterInventoryForOperation(source, "export");

  assert.deepEqual(filtered.projects.map((project) => project.projectKey), ["repo-a"]);
  assert.deepEqual(filtered.projects[0].tasks.map((task) => task.threadId), ["thread-1", "thread-2"]);
  assert.deepEqual(source.projects.map((project) => project.tasks.length), [2, 1]);
});

test("project toggle selects only visible operation tasks", () => {
  const items = buildTaskPickerItems(inventory(), "import");
  const project = items.find((item) => item.id === "project:repo-a");

  assert.deepEqual(project.childThreadIds, ["thread-2"]);
  assert.deepEqual(reduceTaskSelection([], project, true), ["thread-2"]);
});

test("project deselection removes only visible operation tasks", () => {
  const items = buildTaskPickerItems(inventory(), "import");
  const project = items.find((item) => item.id === "project:repo-a");

  assert.deepEqual(
    reduceTaskSelection(["thread-1", "thread-2", "thread-3"], project, false),
    ["thread-1", "thread-3"],
  );
});

test("task rows show state availability Task ID and transfer size", () => {
  const task = buildTaskPickerItems(inventory(), "review")
    .find((item) => item.id === "task:thread-3");

  assert.equal(task.description, "Ready to import | In transfer folder");
  assert.match(task.detail, /Task ID: thread-3/);
  assert.match(task.detail, /estimated task transfer size/i);
  assert.doesNotMatch(task.detail, /Thread ID|sync size/i);
});

test("rows preserve stable snapshot hierarchy and operation filtering", () => {
  const items = buildTaskPickerItems(inventory(), "import");

  assert.deepEqual(items.map((item) => item.id), [
    "project:repo-a",
    "task:thread-2",
    "project:repo-b",
    "task:thread-3",
  ]);
  assert.deepEqual(
    items.filter((item) => item.kind === "project").map((item) => item.detail),
    ["1 task", "1 task"],
  );
});

test("partial task selection leaves the project row unselected", () => {
  const items = buildTaskPickerItems(inventory(), "review");

  assert.deepEqual(selectedPickerItemIds(items, ["thread-1"]), ["task:thread-1"]);
});

test("filtered and unknown technical ids never become selected rows", () => {
  const items = buildTaskPickerItems(inventory(), "import");

  assert.deepEqual(selectedPickerItemIds(items, ["thread-1", "missing-thread"]), []);
  assert.equal(items.some((item) => item.id.includes("missing-thread")), false);
});

test("selection normalization is stable string-only and deduplicated", () => {
  const items = buildTaskPickerItems(inventory(), "review");
  const thread = items.find((item) => item.id === "task:thread-1");

  assert.deepEqual(
    reduceTaskSelection(["thread-2", "thread-2", null, 7], thread, true),
    ["thread-2", "thread-1"],
  );
});

test("technical task ids remain case-sensitive", () => {
  const items = buildTaskPickerItems(inventory(), "review");

  assert.deepEqual(selectedPickerItemIds(items, ["Thread-1", "thread-1"]), ["task:thread-1"]);
});

test("task rows toggle exactly one technical id", () => {
  const items = buildTaskPickerItems(inventory(), "review");
  const task = items.find((item) => item.id === "task:thread-1");

  assert.deepEqual(reduceTaskSelection([], task, true), ["thread-1"]);
  assert.deepEqual(reduceTaskSelection(["thread-1", "thread-2"], task, false), ["thread-2"]);
});
