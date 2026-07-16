const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");

const warnings = [];

function disposable() {
  return { dispose() {} };
}

function createCancelingQuickPick() {
  const handlers = {};
  return {
    items: [],
    selectedItems: [],
    onDidChangeSelection(handler) {
      handlers.change = handler;
      return disposable();
    },
    onDidAccept(handler) {
      handlers.accept = handler;
      return disposable();
    },
    onDidHide(handler) {
      handlers.hide = handler;
      return disposable();
    },
    show() {
      handlers.hide();
    },
    dispose() {},
  };
}

const fakeVscode = {
  window: {
    createQuickPick: createCancelingQuickPick,
    showWarningMessage(message) {
      warnings.push(message);
    },
  },
  QuickPickItemKind: { Separator: -1 },
};

const originalLoad = Module._load;
Module._load = function loadWithVscodeFake(request, parent, isMain) {
  return request === "vscode"
    ? fakeVscode
    : originalLoad.call(this, request, parent, isMain);
};
const { createTaskTransferVscode } = require("../out/taskTransferVscode");
Module._load = originalLoad;

const { taskInventoryWarningMessage } = require("../out/transferPresentation");

test("controller shows the pure Task Transfer warning for unidentified inventory tasks", async () => {
  warnings.length = 0;
  const statuses = [];
  const context = {
    globalState: {
      get: (key, fallback) => key === "syncDir" ? "/transfer" : fallback,
      async update() {},
    },
  };
  const actions = createTaskTransferVscode(context, {
    output: { append() {}, appendLine() {} },
    readAutoTransitions: () => true,
    async resolveExecutable() {
      throw new Error("picker cancellation must stop before transfer execution");
    },
    processEnv: () => ({}),
    async runCommand() {
      return {
        stdout: JSON.stringify({
          inventory_version: 2,
          projects: [],
          issues: [{
            code: "unidentified_remote_task",
            message: "Technical inventory detail.",
            thread_id: "",
          }],
        }),
        stderr: "",
      };
    },
    async refreshUi() {},
    setTransientStatus: (status) => statuses.push(status),
  });

  await actions.importTasks();

  assert.deepEqual(warnings, [taskInventoryWarningMessage()]);
  assert.deepEqual(statuses, ["checking", undefined]);
  assert.doesNotMatch(warnings[0], /remote task files|Sync folder|This device|Thread ID|estimated sync size/i);
});
