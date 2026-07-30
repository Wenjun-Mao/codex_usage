const assert = require("node:assert/strict");
const EventEmitter = require("node:events");
const Module = require("node:module");
const test = require("node:test");

let deferNextQuickPickSelectionEvents = false;

class FakeQuickPick extends EventEmitter {
  constructor() {
    super();
    this._items = [];
    this._selectedItems = [];
    this.activeItems = [];
    this.buttons = [];
    this.value = "";
    this.deferProgrammaticSelectionEvents = deferNextQuickPickSelectionEvents;
    deferNextQuickPickSelectionEvents = false;
    this.queuedSelectionEvents = [];
    this.disposeCount = 0;
    this.disposed = false;
    this.queuedHideListeners = [];
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

  onDidTriggerButton(listener) {
    this.on("button", listener);
    return { dispose: () => this.off("button", listener) };
  }

  show() {
    this.shown = true;
  }

  dispose() {
    this.disposeCount += 1;
    this.disposed = true;
  }

  get selectedItems() {
    return this._selectedItems;
  }

  set selectedItems(items) {
    this._selectedItems = items;
    this.emitProgrammaticSelection(items);
  }

  get items() {
    return this._items;
  }

  set items(items) {
    this._items = items;
    if (this.shown && this._selectedItems.length > 0) {
      this.emitProgrammaticSelection([]);
    }
  }

  select(ids) {
    this._selectedItems = this.items.filter((item) => ids.includes(item.task?.id));
    this.emit("selection", this._selectedItems);
  }

  focus(id) {
    this.activeItems = this.items.filter((item) => item.task?.id === id);
  }

  triggerBack() {
    this.emit("button", fakeVscode.QuickInputButtons.Back);
  }

  emitProgrammaticSelection(items) {
    if (this.deferProgrammaticSelectionEvents && this.shown) {
      this.queuedSelectionEvents.push([...items]);
      return;
    }
    this.emit("selection", items);
  }

  flushProgrammaticSelectionEvents(limit = 20) {
    let delivered = 0;
    while (this.queuedSelectionEvents.length > 0 && delivered < limit) {
      const items = this.queuedSelectionEvents.shift();
      this._selectedItems = items;
      this.emit("selection", items);
      delivered += 1;
    }
    return {
      delivered,
      drained: this.queuedSelectionEvents.length === 0,
    };
  }

  accept() {
    this.emit("accept");
  }

  queueHide() {
    this.queuedHideListeners = this.listeners("hide");
  }

  runQueuedHide() {
    for (const listener of this.queuedHideListeners) {
      listener();
    }
    this.queuedHideListeners = [];
  }
}

const quickPicks = [];
const fakeVscode = {
  QuickPickItemKind: { Separator: -1 },
  QuickInputButtons: { Back: { id: "back" } },
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
        tasks: [
          {
            threadId: "thread-2",
            title: "Planning notes",
            updatedAt: "2026-07-13T12:00:00Z",
            estimatedSyncBytes: 2048,
            availability: "both",
            state: "synced",
            action: "none",
          },
          {
            threadId: "thread-4",
            title: "Import follow-up",
            updatedAt: "2026-07-11T12:00:00Z",
            estimatedSyncBytes: 1024,
            availability: "remote",
            state: "remote_only",
            action: "pull",
          },
        ],
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

test("import uses separate project and task screens with an empty task selection", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("import", buildTaskPickerItems(inventory(), "import"));
  const quickPick = quickPicks.at(-1);

  assert.equal(quickPick.title, "Import Tasks: Choose a Project");
  assert.equal(quickPick.placeholder, "Choose one project to import tasks into.");
  assert.equal(quickPick.canSelectMany, false);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "project:repo-a",
    "project:repo-b",
  ]);

  quickPick.focus("project:repo-a");
  quickPick.accept();

  assert.equal(quickPick.title, "Import Tasks: Select Tasks for Repo A");
  assert.equal(quickPick.placeholder, "Search tasks in Repo A.");
  assert.equal(quickPick.canSelectMany, true);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "task:thread-2",
    "task:thread-4",
  ]);
  assert.deepEqual(quickPick.selectedItems, []);

  quickPick.select(["task:thread-4"]);
  quickPick.accept();
  assert.deepEqual(await result, { projectKey: "repo-a", threadIds: ["thread-4"] });
});

test("back returns to the project screen and clears task state", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("import", buildTaskPickerItems(inventory(), "import"));
  const quickPick = quickPicks.at(-1);

  quickPick.focus("project:repo-a");
  quickPick.accept();
  quickPick.select(["task:thread-4"]);
  quickPick.value = "follow-up";
  quickPick.triggerBack();

  assert.equal(quickPick.title, "Import Tasks: Choose a Project");
  assert.equal(quickPick.canSelectMany, false);
  assert.equal(quickPick.value, "");
  assert.deepEqual(quickPick.selectedItems, []);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "project:repo-a",
    "project:repo-b",
  ]);

  quickPick.focus("project:repo-a");
  quickPick.accept();
  assert.deepEqual(quickPick.selectedItems, []);

  quickPick.select(["task:thread-2"]);
  quickPick.accept();
  assert.deepEqual(await result, { projectKey: "repo-a", threadIds: ["thread-2"] });
});

test("task screen rejects an empty selection", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("import", buildTaskPickerItems(inventory(), "import"));
  const quickPick = quickPicks.at(-1);

  quickPick.focus("project:repo-a");
  quickPick.accept();
  quickPick.accept();

  assert.equal(quickPick.title, "Select at least one Codex task to import");

  quickPick.select(["task:thread-2"]);
  quickPick.accept();
  assert.deepEqual(await result, { projectKey: "repo-a", threadIds: ["thread-2"] });
});

test("a delayed empty selection event cannot undo the accepted task selection", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("export", buildTaskPickerItems(inventory(), "export"));
  const quickPick = quickPicks.at(-1);

  quickPick.focus("project:repo-a");
  quickPick.accept();
  quickPick.select(["task:thread-2"]);
  quickPick.emit("selection", []);
  quickPick.accept();

  assert.equal(quickPick.disposed, true);
  assert.deepEqual(await result, { projectKey: "repo-a", threadIds: ["thread-2"] });
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

test("review project shortcut settles once when deferred events and hide arrive late", async () => {
  quickPicks.length = 0;
  deferNextQuickPickSelectionEvents = true;
  const result = showTaskTransferPicker("review", buildTaskPickerItems(inventory(), "review"));
  const quickPick = quickPicks.at(-1);
  let settlementCount = 0;
  let settledSelection;
  result.then((selection) => {
    settlementCount += 1;
    settledSelection = selection;
  });

  quickPick.select(["project:repo-a"]);
  assert.deepEqual(quickPick.selectedItems.map((item) => item.task?.id), [
    "project:repo-a",
    "task:thread-2",
    "task:thread-4",
  ]);
  assert.equal(quickPick.queuedSelectionEvents.length, 1);

  quickPick.queueHide();
  quickPick.accept();
  const deferredEvents = quickPick.flushProgrammaticSelectionEvents();
  quickPick.runQueuedHide();

  const selection = await result;
  assert.deepEqual(selection, { threadIds: ["thread-2", "thread-4"] });
  assert.deepEqual(settledSelection, selection);
  assert.equal(settlementCount, 1);
  assert.deepEqual(deferredEvents, { delivered: 1, drained: true });
  assert.equal(quickPick.disposeCount, 1);
});
