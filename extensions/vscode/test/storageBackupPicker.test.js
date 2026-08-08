const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");

const calls = [];
const fakeVscode = {
  window: {
    async showQuickPick(items, options) {
      calls.push({ items, options });
      return items[0];
    },
  },
};
const originalLoad = Module._load;
Module._load = function loadWithVscodeFake(request, parent, isMain) {
  return request === "vscode" ? fakeVscode : originalLoad.call(this, request, parent, isMain);
};
const { chooseStorageTree } = require("../out/storageBackupPicker");
Module._load = originalLoad;

const tree = {
  rootTaskId: "root-123", title: "Largest task", projectKey: "repo-a", projectLabel: "Repo A",
  totalBytes: 2048, rootBytes: 1024, descendantBytes: 1024, descendantCount: 1, physicalFileCount: 2,
  hasMissingRoot: false, hasRelationshipCycle: false, duplicateFileCount: 0, metadataDiagnostics: [],
  recoveryReady: true,
};

test("backup picker is project-first then chooses exactly one task tree", async () => {
  calls.length = 0;
  const selected = await chooseStorageTree([{ projectKey: "repo-a", projectLabel: "Repo A", trees: [tree] }]);
  assert.equal(selected.rootTaskId, "root-123");
  assert.equal(calls[0].options.title, "Back Up Task: Choose a Project");
  assert.equal(calls[1].options.title, "Back Up Task: Choose a Task from Repo A");
  assert.equal(calls[1].options.canPickMany, undefined);
  assert.match(calls[1].items[0].detail, /root 1\.00 KiB/);
});
