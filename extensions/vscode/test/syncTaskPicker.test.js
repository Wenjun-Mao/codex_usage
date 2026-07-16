const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildTaskPickerItems,
  reduceTaskSelection,
  selectedPickerItemIds,
} = require("../out/syncTaskPicker");

function inventory() {
  return {
    inventoryVersion: 1,
    projects: [
      {
        projectKey: "repo-a",
        projectLabel: "Repo A",
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

test("project rows toggle current child tasks without selecting future ids", () => {
  const items = buildTaskPickerItems(inventory(), []);
  const project = items.find((item) => item.kind === "project" && item.projectKey === "repo-a");
  const selected = reduceTaskSelection([], project, true);

  assert.deepEqual(selected, ["thread-1", "thread-2"]);
  assert.deepEqual(selectedPickerItemIds(items, selected), [
    "project:repo-a",
    "task:thread-1",
    "task:thread-2",
  ]);
});

test("a filtered project toggle still uses every snapshot child", () => {
  const items = buildTaskPickerItems(inventory(), []);
  const project = items.find((item) => item.id === "project:repo-a");
  const visibleRows = items.filter((item) => item.label.includes("Persona"));

  assert.equal(visibleRows.some((item) => item.threadId === "thread-2"), false);
  assert.deepEqual(reduceTaskSelection([], project, true), ["thread-1", "thread-2"]);
});

test("project deselection removes every current child and preserves other selections", () => {
  const items = buildTaskPickerItems(inventory(), []);
  const project = items.find((item) => item.id === "project:repo-a");

  assert.deepEqual(
    reduceTaskSelection(["thread-1", "thread-3", "thread-2", "future-thread"], project, false),
    ["thread-3", "future-thread"],
  );
});

test("partial task selection leaves the project row unselected", () => {
  const items = buildTaskPickerItems(inventory(), ["thread-1"]);

  assert.deepEqual(selectedPickerItemIds(items, ["thread-1"]), ["task:thread-1"]);
});

test("missing stored ids remain selected under unavailable tasks", () => {
  const items = buildTaskPickerItems(inventory(), ["missing-thread"]);
  const separator = items.find((item) => item.kind === "separator");
  const missing = items.find((item) => item.kind === "unavailable");

  assert.equal(separator.label, "Unavailable selected tasks");
  assert.equal(missing.threadId, "missing-thread");
  assert.deepEqual(selectedPickerItemIds(items, ["missing-thread"]), ["unavailable:missing-thread"]);
});

test("rows preserve snapshot hierarchy and sort unavailable ids", () => {
  const items = buildTaskPickerItems(inventory(), ["z-missing", "thread-2", "a-missing"]);

  assert.deepEqual(
    items.map((item) => item.id),
    [
      "project:repo-a",
      "task:thread-1",
      "task:thread-2",
      "project:repo-b",
      "task:thread-3",
      "separator:unavailable",
      "unavailable:a-missing",
      "unavailable:z-missing",
    ],
  );
});

test("task rows use Task Transfer availability, task id, and estimated size vocabulary", () => {
  const taskItems = buildTaskPickerItems(inventory(), []).filter((item) => item.kind === "task");

  assert.deepEqual(
    taskItems.map((item) => item.description),
    ["On this computer", "On both", "In transfer folder"],
  );
  assert.equal(taskItems[0].detail, "Task ID: thread-1 | Estimated task transfer size: 1.5 KB");
  assert.equal(taskItems[2].detail, "Task ID: thread-3 | Estimated task transfer size: 512 B");
  assert.doesNotMatch(JSON.stringify(taskItems), /This device|Sync folder|Thread ID|estimated sync size/i);
  assert.equal(taskItems[0].childThreadIds.length, 0);
});

test("unavailable task rows display a Task ID without a Thread ID label", () => {
  const unavailable = buildTaskPickerItems(inventory(), ["missing-thread"])
    .find((item) => item.kind === "unavailable");

  assert.equal(unavailable.detail, "Task ID: missing-thread");
  assert.doesNotMatch(unavailable.detail, /^Thread ID:/i);
});

test("project rows report exact task counts", () => {
  const projectItems = buildTaskPickerItems(inventory(), []).filter((item) => item.kind === "project");

  assert.deepEqual(
    projectItems.map((item) => item.detail),
    ["2 tasks", "1 task"],
  );
});

test("empty initial selection selects no picker rows", () => {
  const items = buildTaskPickerItems(inventory(), []);

  assert.deepEqual(selectedPickerItemIds(items, []), []);
});

test("selection normalization is stable, string-only, deduplicated, and case-sensitive", () => {
  const items = buildTaskPickerItems(inventory(), ["Missing", "missing", "Missing", null, 7]);
  const unavailableItems = items.filter((item) => item.kind === "unavailable");
  const thread = items.find((item) => item.id === "task:thread-1");
  const separator = items.find((item) => item.kind === "separator");

  assert.deepEqual(
    unavailableItems.map((item) => item.threadId),
    ["Missing", "missing"],
  );
  assert.deepEqual(reduceTaskSelection(["thread-2", "thread-2", null], thread, true), [
    "thread-2",
    "thread-1",
  ]);
  assert.deepEqual(reduceTaskSelection(["thread-2"], separator, true), ["thread-2"]);
});

test("task and unavailable rows toggle exactly one technical id", () => {
  const items = buildTaskPickerItems(inventory(), ["missing-thread"]);
  const task = items.find((item) => item.id === "task:thread-1");
  const unavailable = items.find((item) => item.id === "unavailable:missing-thread");

  assert.deepEqual(reduceTaskSelection([], task, true), ["thread-1"]);
  assert.deepEqual(reduceTaskSelection(["thread-1", "missing-thread"], unavailable, false), [
    "thread-1",
  ]);
});
