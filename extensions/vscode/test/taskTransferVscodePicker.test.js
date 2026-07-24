const assert = require("node:assert/strict");
const EventEmitter = require("node:events");
const Module = require("node:module");
const test = require("node:test");

class FakeQuickPick extends EventEmitter {
  constructor() {
    super();
    this.items = [];
    this._selectedItems = [];
    this.disposed = false;
    this.shown = false;
  }

  onDidChangeSelection(listener) {
    this.on("selection", listener);
    return { dispose: () => this.off("selection", listener) };
  }

  onDidAccept(listener) {
    this.on("accept", listener);
    return { dispose: () => this.off("accept", listener) };
  }

  onDidHide(listener) {
    this.on("hide", listener);
    return { dispose: () => this.off("hide", listener) };
  }

  show() {
    this.shown = true;
  }

  dispose() {
    this.disposed = true;
  }

  get selectedItems() {
    return this._selectedItems;
  }

  set selectedItems(items) {
    this._selectedItems = items;
    this.emit("selection", items);
  }

  select(ids) {
    this.selectedItems = this.items.filter((item) => ids.includes(item.task?.id));
  }

  accept() {
    this.emit("accept");
  }
}

const quickPicks = [];
const fakeVscode = {
  QuickPickItemKind: { Separator: -1 },
  window: {
    createQuickPick() {
      const quickPick = new FakeQuickPick();
      quickPicks.push(quickPick);
      return quickPick;
    },
  },
};
const originalLoad = Module._load;
Module._load = function loadWithVscodeFake(request, parent, isMain) {
  return request === "vscode" ? fakeVscode : originalLoad.call(this, request, parent, isMain);
};
const { showTaskTransferPicker } = require("../out/taskTransferVscodePicker");
const { buildTaskPickerItems } = require("../out/syncTaskPicker");
Module._load = originalLoad;

function inventory() {
  return {
    inventoryVersion: 2,
    projects: [
      {
        projectKey: "repo-a",
        projectLabel: "Repo A",
        identityKind: "git",
        candidateRoots: [],
        tasks: [{
          threadId: "thread-2",
          title: "Planning notes",
          updatedAt: "2026-07-13T12:00:00Z",
          estimatedSyncBytes: 2048,
          availability: "both",
          state: "synced",
          action: "none",
        }],
      },
      {
        projectKey: "repo-b",
        projectLabel: "Repo B",
        identityKind: "path",
        candidateRoots: [],
        tasks: [{
          threadId: "thread-3",
          title: "Remote task",
          updatedAt: "2026-07-12T12:00:00Z",
          estimatedSyncBytes: 512,
          availability: "remote",
          state: "remote_only",
          action: "pull",
        }],
      },
    ],
    issues: [],
  };
}

test("import picker activates one project and returns its independent subset", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("import", buildTaskPickerItems(inventory(), "import"));
  const quickPick = quickPicks.at(-1);

  assert.equal(quickPick.title, "Import Tasks: Choose One Project");
  assert.equal(quickPick.placeholder, "One project per import. All tasks start selected.");
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), ["project:repo-a", "project:repo-b"]);

  quickPick.select(["project:repo-a"]);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "project:repo-a", "task:thread-2", "project:repo-b",
  ]);
  assert.deepEqual(quickPick.selectedItems.map((item) => item.task?.id), [
    "project:repo-a", "task:thread-2",
  ]);
  assert.equal(quickPick.items[0].description, "Selected project");

  quickPick.select(["project:repo-a"]);
  assert.equal(quickPick.items[0].description, "Selected project");
  assert.deepEqual(quickPick.selectedItems.map((item) => item.task?.id), ["project:repo-a"]);

  quickPick.select(["project:repo-a", "project:repo-b"]);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "project:repo-a", "project:repo-b", "task:thread-3",
  ]);
  assert.deepEqual(quickPick.selectedItems.map((item) => item.task?.id), [
    "project:repo-b", "task:thread-3",
  ]);

  quickPick.accept();
  quickPick.emit("hide");
  assert.deepEqual(await result, { projectKey: "repo-b", threadIds: ["thread-3"] });
});

test("review picker copy makes cross-project selection explicit", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("review", buildTaskPickerItems(inventory(), "review"));
  const quickPick = quickPicks.at(-1);

  assert.equal(quickPick.title, "Review Tasks Across Projects");
  assert.equal(quickPick.placeholder, "Select any tasks to compare without copying files.");
  quickPick.select(["task:thread-2", "task:thread-3"]);
  quickPick.accept();

  assert.deepEqual(await result, { threadIds: ["thread-2", "thread-3"] });
});
