const assert = require("node:assert/strict");
const test = require("node:test");

const { migrateTaskTransferState } = require("../out/taskTransferState");
const { createTaskTransferVscodeStateStore } = require("../out/taskTransferVscodeState");

function fakeVscodeState(options = {}) {
  const calls = [];
  const globalState = new Map([
    ["syncDir", options.folder ?? "/transfer"],
    ["syncThreadIds", ["task-1"]],
    ["syncSelectionVersion", 2],
  ]);
  const values = {
    base: {
      legacyFolder: options.legacyFolder ?? "/legacy",
      global: options.globalEnabled ?? true,
      workspace: options.workspaceEnabled ?? false,
    },
    "/repo-a": { folder: options.folderAEnabled ?? true },
    "/repo-b": { folder: options.folderBEnabled ?? false },
  };
  const folders = [
    { uri: { fsPath: "/repo-a" } },
    { uri: { fsPath: "/repo-b" } },
  ];

  function configuration(resource) {
    const scope = resource ? resource.fsPath : "base";
    return {
      get(key, fallback) {
        if (key === "sync.dir" && scope === "base") {
          return values.base.legacyFolder;
        }
        return fallback;
      },
      inspect(key) {
        assert.equal(key, "sync.enabled");
        if (scope === "base") {
          return {
            globalValue: values.base.global,
            workspaceValue: values.base.workspace,
          };
        }
        return { workspaceFolderValue: values[scope].folder };
      },
      async update(key, value, target) {
        calls.push(["configuration", scope, key, value, target]);
        const failure = `${scope}:${target}`;
        if ((options.failUpdates ?? []).includes(failure)) {
          throw new Error(`failed ${failure}`);
        }
        if (target === "global") {
          values.base.global = value;
        } else if (target === "workspace") {
          values.base.workspace = value;
        } else {
          values[scope].folder = value;
        }
      },
    };
  }

  return {
    calls,
    globalState,
    adapter: {
      globalState: {
        get: (key, fallback) => globalState.has(key) ? globalState.get(key) : fallback,
        async update(key, value) {
          calls.push(["globalState", key, value]);
          if (value === undefined) {
            globalState.delete(key);
          } else {
            globalState.set(key, value);
          }
        },
      },
      configuration,
      workspaceFolders: () => folders,
      targets: {
        global: "global",
        workspace: "workspace",
        workspaceFolder: "workspaceFolder",
      },
    },
  };
}

test("adapter clears global workspace and every folder target in order", async () => {
  const fake = fakeVscodeState();
  const errors = [];

  await migrateTaskTransferState(
    createTaskTransferVscodeStateStore(fake.adapter),
    (message) => errors.push(message),
  );

  assert.deepEqual(fake.calls, [
    ["globalState", "syncThreadIds", undefined],
    ["globalState", "syncSelectionVersion", undefined],
    ["configuration", "base", "sync.enabled", undefined, "global"],
    ["configuration", "base", "sync.enabled", undefined, "workspace"],
    ["configuration", "/repo-a", "sync.enabled", undefined, "workspaceFolder"],
    ["configuration", "/repo-b", "sync.enabled", undefined, "workspaceFolder"],
  ]);
  assert.deepEqual(errors, []);
});

test("adapter cleanup is idempotent", async () => {
  const fake = fakeVscodeState();
  const store = createTaskTransferVscodeStateStore(fake.adapter);

  await migrateTaskTransferState(store, () => undefined);
  fake.calls.length = 0;
  await migrateTaskTransferState(store, () => undefined);

  assert.deepEqual(fake.calls, [
    ["globalState", "syncThreadIds", undefined],
    ["globalState", "syncSelectionVersion", undefined],
  ]);
});

test("adapter attempts every target and reports update failures independently", async () => {
  const fake = fakeVscodeState({
    failUpdates: ["base:global", "/repo-b:workspaceFolder"],
  });
  const errors = [];

  await assert.doesNotReject(
    migrateTaskTransferState(
      createTaskTransferVscodeStateStore(fake.adapter),
      (message) => errors.push(message),
    ),
  );

  assert.deepEqual(
    fake.calls.filter((call) => call[0] === "configuration").map((call) => [call[1], call[4]]),
    [
      ["base", "global"],
      ["base", "workspace"],
      ["/repo-a", "workspaceFolder"],
      ["/repo-b", "workspaceFolder"],
    ],
  );
  assert.equal(errors.length, 2);
  assert.match(errors[0], /global/);
  assert.match(errors[1], /folder:\/repo-b/);
});
