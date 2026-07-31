const assert = require("node:assert/strict");
const test = require("node:test");

const { filterInventoryForOperation } = require("../out/syncInventory");
const {
  activateTaskPickerProject,
  buildTaskPickerItems,
  initialTaskPickerSelection,
  reduceTaskSelection,
  reduceTransferTaskSelection,
  selectedPickerItemIds,
  selectedTaskPickerItemIds,
  visibleTaskPickerItems,
} = require("../out/syncTaskPicker");

function inventory() {
  return {
    inventoryVersion: 3,
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
          },
          {
            threadId: "thread-2",
            title: "Planning notes",
            updatedAt: "2026-07-13T12:00:00Z",
            estimatedSyncBytes: 2048,
            availability: "both",
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

test("import lists transfer-folder tasks", () => {
  const items = buildTaskPickerItems(inventory(), "import");

  assert.deepEqual(taskIds(items), ["thread-2", "thread-3"]);
});

test("transfer starts with project rows only and activating a project selects no tasks", () => {
  const rows = buildTaskPickerItems(inventory(), "import");
  const initial = initialTaskPickerSelection("import");

  assert.deepEqual(
    visibleTaskPickerItems(rows, initial, "import").map((item) => item.id),
    ["project:repo-a", "project:repo-b"],
  );

  const active = activateTaskPickerProject(rows, "repo-a");
  assert.deepEqual(active, {
    activeProjectKey: "repo-a",
    selectedThreadIds: [],
  });
  assert.deepEqual(
    visibleTaskPickerItems(rows, active, "import").map((item) => item.id),
    ["task:thread-2"],
  );
  assert.deepEqual(selectedTaskPickerItemIds(rows, active, "import"), []);
});

test("export starts empty and searches only the active project's tasks", () => {
  const rows = buildTaskPickerItems(inventory(), "export");
  const initial = initialTaskPickerSelection("export");
  const active = activateTaskPickerProject(rows, "repo-a");

  assert.deepEqual(initial, {
    activeProjectKey: undefined,
    selectedThreadIds: [],
  });
  assert.deepEqual(
    visibleTaskPickerItems(rows, active, "export").map((row) => row.kind),
    ["task", "task"],
  );
});

test("switching projects discards task state and never selects the project row", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const repoA = activateTaskPickerProject(rows, "repo-a");
  const selectedRepoA = reduceTransferTaskSelection(
    repoA,
    rows.find((row) => row.id === "task:thread-1"),
    true,
  );
  const repoB = activateTaskPickerProject(rows, "repo-b");

  assert.deepEqual(selectedRepoA.selectedThreadIds, ["thread-1"]);
  assert.deepEqual(selectedTaskPickerItemIds(rows, selectedRepoA, "export"), [
    "task:thread-1",
  ]);
  assert.deepEqual(repoB, {
    activeProjectKey: "repo-b",
    selectedThreadIds: [],
  });
});

test("a task outside the active project cannot enter transfer selection", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const active = activateTaskPickerProject(rows, "repo-a");
  const foreignTask = rows.find((row) => row.id === "task:thread-3");

  assert.deepEqual(
    reduceTransferTaskSelection(active, foreignTask, true),
    active,
  );
});

test("review retains fresh cross-project selection", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const state = initialTaskPickerSelection("review");

  assert.equal(state.activeProjectKey, undefined);
  assert.deepEqual(state.selectedThreadIds, []);
  assert.deepEqual(visibleTaskPickerItems(rows, state, "review"), rows);
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

test("task rows show availability Task ID and transfer size", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const local = rows.find((row) => row.id === "task:thread-1");
  const both = rows.find((row) => row.id === "task:thread-2");
  const remote = rows.find((row) => row.id === "task:thread-3");

  assert.equal(local.description, "On this computer");
  assert.equal(remote.description, "In transfer folder");
  assert.equal(both.description, "On both");
  assert.match(remote.detail, /Task ID: thread-3/);
  assert.match(remote.detail, /estimated task transfer size/i);
  assert.doesNotMatch(remote.detail, /Thread ID|sync size/i);
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
