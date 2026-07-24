const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");

const {
  TaskTransferController,
  configurationScopeIds,
  workspaceRootPaths,
} = require("../out/taskTransfer");

const calls = {
  dialogs: [],
  external: [],
  info: [],
  warning: [],
  error: [],
  progress: [],
  quickPicks: [],
  stats: [],
};

function resetCalls() {
  for (const value of Object.values(calls)) value.length = 0;
}

const fakeVscode = {
  ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
  ProgressLocation: { Window: 10 },
  QuickPickItemKind: { Separator: -1 },
  Uri: { file: (fsPath) => ({ fsPath }) },
  env: {
    async openExternal(uri) {
      calls.external.push(uri.fsPath);
    },
  },
  window: {
    async showOpenDialog(options) {
      calls.dialogs.push(options);
      return [];
    },
    async showQuickPick(items, options) {
      calls.quickPicks.push([items, options]);
      return undefined;
    },
    showInformationMessage(message) {
      calls.info.push(message);
    },
    showWarningMessage(message) {
      calls.warning.push(message);
    },
    showErrorMessage(message) {
      calls.error.push(message);
    },
    async withProgress(options, callback) {
      calls.progress.push(options);
      return callback();
    },
  },
  workspace: {
    workspaceFolders: [
      { uri: { fsPath: "/Repo" } },
      { uri: { fsPath: " /Other " } },
    ],
    fs: {
      async stat(uri) {
        calls.stats.push(uri.fsPath);
      },
    },
    getConfiguration() {
      return {
        get: (_key, fallback) => fallback,
        inspect: () => undefined,
        async update() {},
      };
    },
  },
};

const originalLoad = Module._load;
Module._load = function loadWithVscodeFake(request, parent, isMain) {
  return request === "vscode" ? fakeVscode : originalLoad.call(this, request, parent, isMain);
};
const { createTaskTransferVscodePort } = require("../out/taskTransferVscode");
Module._load = originalLoad;

function inventoryJson() {
  return JSON.stringify({ inventory_version: 2, projects: [], issues: [] });
}

function statusThread(overrides = {}) {
  return {
    thread_id: "task-1",
    state: "synced",
    action: "none",
    reason: "matching task bytes",
    local_path: "/codex/task-1.jsonl",
    remote_path: "/transfer/tasks/task-1.jsonl",
    local_sha256: "same",
    remote_sha256: "same",
    base_sha256: "same",
    updated_at: "2026-07-16T12:00:00Z",
    source_relative_path: "2026/07/16/task-1.jsonl",
    project_key: "repo",
    project_label: "Repo",
    memory_database_rows: 0,
    ...overrides,
  };
}

function context(folder = "/transfer") {
  const writes = [];
  return {
    writes,
    globalStorageUri: { fsPath: "/storage" },
    globalState: {
      get: (key, fallback) => key === "syncDir" ? folder : fallback,
      async update(key, value) {
        writes.push([key, value]);
      },
    },
  };
}

function dependencies(overrides = {}) {
  const commands = [];
  const processCalls = [];
  const statuses = [];
  return {
    commands,
    processCalls,
    statuses,
    output: { append() {}, appendLine() {} },
    async resolveExecutable() { return "/bin/codex-usage"; },
    processEnv: () => ({ TEST: "1" }),
    async runCommand(args) {
      commands.push(args);
      return { stdout: inventoryJson(), stderr: "" };
    },
    async runSyncProcess(options) {
      processCalls.push(options);
      options.onProgress({ type: "sync_progress", phase: options.args[1] === "pull" ? "pulling" : "pushing" });
      return {
        exitCode: 0,
        stdout: "{}",
        stderr: "",
        result: overrides.processResult ?? {
          outcome: "completed",
          counts: { discovered: 1, selected: 1, remote: 0, pulled: 1, pushed: 0, unchanged: 0, conflicts: 0, issues: 0 },
          timings_ms: { discovery: 1, planning: 1, pull: 1, push: 0, index: 1, total: 4 },
          threads: [], pulled: [], pushed: [], issues: [],
        },
      };
    },
    async refreshUi() {},
    setTransientStatus(status) { statuses.push(status); },
    ...overrides,
  };
}

function executionRequest() {
  return {
    syncDir: "/transfer",
    threadIds: ["task-1"],
    autoTransitions: false,
    candidateProjectRoots: ["/Repo"],
    projectBindings: [{
      projectKey: "https://github.com/example/project",
      path: "/Repo",
      confirmedUnverified: false,
    }],
  };
}

test("workspace roots are trimmed deduplicated and preserve first spelling", () => {
  assert.deepEqual(workspaceRootPaths([
    { uri: { fsPath: "/Repo" } },
    { uri: { fsPath: "/Repo" } },
    { uri: { fsPath: " /Other " } },
  ]), ["/Repo", "/Other"]);
  assert.deepEqual(configurationScopeIds(undefined), ["global", "workspace"]);
  assert.deepEqual(configurationScopeIds(fakeVscode.workspace.workspaceFolders), [
    "global", "workspace", "folder:/Repo", "folder:/Other",
  ]);
});

test("adapter source never writes private Codex project registries", () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/taskTransferVscode.ts"), "utf8");
  assert.doesNotMatch(source, /\.codex-global-state\.json|sqlite/i);
  assert.match(source, /workspace\.workspaceFolders/);
  assert.match(source, /ConfigurationTarget\.Global/);
  assert.match(source, /ConfigurationTarget\.Workspace/);
  assert.match(source, /ConfigurationTarget\.WorkspaceFolder/);
  for (const helper of ["workspaceRootPaths", "configurationScopeIds"]) {
    assert.match(source, new RegExp(helper));
  }
});

test("picker source gives every operation its approved project-aware title", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "../src/taskTransferVscodePicker.ts"),
    "utf8",
  );
  for (const title of [
    "Import Tasks: Choose One Project",
    "Export Tasks: Choose One Project",
    "Review Tasks Across Projects",
  ]) {
    assert.match(source, new RegExp(title));
  }
  assert.doesNotMatch(source, /Select tasks for Task Transfer/);
});

test("port transports workspace roots and maps import progress to user-facing transient status", async () => {
  resetCalls();
  const deps = dependencies();
  const port = createTaskTransferVscodePort(context(), deps);

  assert.deepEqual(port.workspaceRoots(), ["/Repo", "/Other"]);
  await port.loadInventory({
    syncDir: "/transfer",
    autoTransitions: false,
    candidateProjectRoots: port.workspaceRoots(),
  });
  await port.execute("import", executionRequest());

  assert.deepEqual(calls.stats, ["/transfer"]);
  assert.deepEqual(deps.commands[0], [
    "sync", "inventory", "--json", "--sync-dir", "/transfer",
    "--candidate-project-root", "/Repo", "--candidate-project-root", "/Other",
    "--no-auto-transitions",
  ]);
  assert.deepEqual(deps.processCalls[0].args.slice(0, 3), ["sync", "pull", "--json"]);
  assert.deepEqual(deps.statuses, ["importing"]);
});

test("port maps export to push and review to status exactly once", async () => {
  resetCalls();
  const deps = dependencies({
    async runCommand(args) {
      deps.commands.push(args);
      return { stdout: JSON.stringify({ threads: [], issues: [] }), stderr: "" };
    },
  });
  const port = createTaskTransferVscodePort(context(), deps);
  await port.execute("export", executionRequest());
  await port.review(executionRequest());

  assert.deepEqual(deps.processCalls[0].args.slice(0, 3), ["sync", "push", "--json"]);
  assert.deepEqual(deps.statuses, ["exporting"]);
  assert.deepEqual(deps.commands[0].slice(0, 3), ["sync", "status", "--json"]);
  assert.equal(deps.processCalls.length, 1);
  assert.equal(deps.commands.length, 1);
});

test("review adapter rejects malformed native status output", async () => {
  resetCalls();
  const deps = dependencies({
    async runCommand(args) {
      deps.commands.push(args);
      return {
        stdout: JSON.stringify({ threads: null, issues: [7, {}] }),
        stderr: "",
      };
    },
  });
  const port = createTaskTransferVscodePort(context(), deps);

  await assert.rejects(
    () => port.review(executionRequest()),
    /Invalid Codex sync status/,
  );
  assert.equal(deps.commands.length, 1);
});

test("review adapter rejects semantically invalid native status rows", async () => {
  resetCalls();
  const deps = dependencies({
    async runCommand(args) {
      deps.commands.push(args);
      return {
        stdout: JSON.stringify({
          threads: [statusThread({ state: "synced", action: "pull" })],
          issues: [],
        }),
        stderr: "",
      };
    },
  });
  const port = createTaskTransferVscodePort(context(), deps);

  await assert.rejects(
    () => port.review(executionRequest()),
    /Invalid Codex sync status/,
  );
  assert.equal(deps.commands.length, 1);
});

test("execution adapter preserves structured partial completion", async () => {
  resetCalls();
  const partial = {
    outcome: "issue",
    counts: {
      discovered: 2, selected: 2, remote: 2, pulled: 1, pushed: 0,
      unchanged: 0, conflicts: 0, issues: 1,
    },
    timings_ms: { discovery: 1, planning: 1, pull: 1, push: 0, index: 1, total: 4 },
    threads: [],
    pulled: ["task-1"],
    pushed: [],
    issues: [{ code: "transfer_filesystem_failure", message: "state write failed", thread_id: "" }],
  };
  const deps = dependencies({ processResult: partial });
  const port = createTaskTransferVscodePort(context(), deps);

  const result = await port.execute("import", executionRequest());

  assert.deepEqual(result, partial);
  assert.deepEqual(result.pulled, ["task-1"]);
});

test("missing remembered folder is actionable and never rewrites state", async () => {
  resetCalls();
  const ctx = context("/offline");
  const deps = dependencies();
  fakeVscode.workspace.fs.stat = async (uri) => {
    calls.stats.push(uri.fsPath);
    throw new Error("offline");
  };
  const controller = new TaskTransferController(
    createTaskTransferVscodePort(ctx, deps),
    () => true,
  );

  await controller.importTasks();

  assert.deepEqual(calls.error, [
    "The transfer folder is not available: /offline. Choose another transfer folder and try again.",
  ]);
  assert.deepEqual(ctx.writes, []);
  assert.deepEqual(deps.commands, []);
});
