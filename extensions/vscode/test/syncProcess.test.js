const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { PassThrough } = require("node:stream");
const test = require("node:test");

const { runSyncProcess } = require("../out/syncProcess");

function completedResult(countOverrides = {}) {
  return {
    outcome: "completed",
    counts: {
      discovered: 1,
      selected: 1,
      remote: 0,
      pulled: 0,
      pushed: 1,
      unchanged: 0,
      conflicts: 0,
      issues: 0,
      ...countOverrides,
    },
    timings_ms: { discovery: 1, planning: 1, pull: 0, push: 1, index: 1, total: 4 },
    threads: [],
    pulled: [],
    pushed: ["thread-1"],
    issues: [],
  };
}

function conflictResult() {
  return {
    ...completedResult({ pushed: 0, conflicts: 1 }),
    outcome: "conflict",
    pushed: [],
  };
}

function fakeSyncChild({ stderrChunks = [], stdout = "", stdoutChunks, exitCode = 0 }) {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  queueMicrotask(() => {
    for (const chunk of stderrChunks) {
      child.stderr.write(chunk);
    }
    if (stdoutChunks) {
      for (const chunk of stdoutChunks) {
        child.stdout.write(chunk);
      }
      child.stdout.end();
    } else {
      child.stdout.end(stdout);
    }
    child.stderr.end();
    child.emit("close", exitCode);
  });
  return child;
}

function processOptions(overrides = {}) {
  return {
    executablePath: "/bin/codex-usage",
    args: ["sync", "run", "--json"],
    env: { CODEX_USAGE_CACHE_DIR: "/cache" },
    onProgress: () => undefined,
    onOutput: () => undefined,
    ...overrides,
  };
}

function splitUtf8(text, character, byteOffset) {
  const bytes = Buffer.from(text);
  const characterStart = bytes.indexOf(Buffer.from(character));
  assert.notEqual(characterStart, -1);
  return [bytes.subarray(0, characterStart + byteOffset), bytes.subarray(characterStart + byteOffset)];
}

test("runSyncProcess spawns once and parses split, grouped, and residual progress lines", async () => {
  const phases = [];
  const rawOutput = [];
  const stderrChunks = [
    "ordinary diagnostic\n{\"type\":\"sync_",
    "progress\",\"phase\":\"scanning\"}\n{\"type\":\"sync_progress\",\"phase\":\"pulling\"}\n",
    '{"type":"sync_progress","phase":"pushing"}',
  ];
  const stdout = JSON.stringify(completedResult());
  let spawnCount = 0;
  let spawnCall;

  const completion = await runSyncProcess(
    processOptions({
      onProgress: (event) => phases.push(event.phase),
      onOutput: (text) => rawOutput.push(text),
      spawnProcess: (executablePath, args, options) => {
        spawnCount += 1;
        spawnCall = { executablePath, args, options };
        return fakeSyncChild({ stderrChunks, stdout, exitCode: 0 });
      },
    }),
  );

  assert.equal(spawnCount, 1);
  assert.deepEqual(spawnCall, {
    executablePath: "/bin/codex-usage",
    args: ["sync", "run", "--json"],
    options: {
      shell: false,
      windowsHide: true,
      env: { CODEX_USAGE_CACHE_DIR: "/cache" },
    },
  });
  assert.deepEqual(phases, ["scanning", "pulling", "pushing"]);
  assert.equal(rawOutput.join(""), stderrChunks.join("") + stdout);
  assert.equal(completion.exitCode, 0);
  assert.deepEqual(completion.result, completedResult());
});

test("runSyncProcess preserves a multibyte stdout character split across Buffer chunks", async () => {
  const result = completedResult();
  result.pushed = ["thread-雪"];
  const stdout = JSON.stringify(result);
  const rawOutput = [];

  const completion = await runSyncProcess(
    processOptions({
      onOutput: (text) => rawOutput.push(text),
      spawnProcess: () =>
        fakeSyncChild({
          stdoutChunks: splitUtf8(stdout, "雪", 1),
        }),
    }),
  );

  assert.equal(completion.stdout, stdout);
  assert.deepEqual(completion.result, result);
  assert.equal(rawOutput.join(""), stdout);
});

test("runSyncProcess preserves multibyte stderr diagnostics split across Buffer chunks", async () => {
  const stderr = '诊断: 同步\n{"type":"sync_progress","phase":"pulling"}\n';
  const phases = [];

  const completion = await runSyncProcess(
    processOptions({
      onProgress: (event) => phases.push(event.phase),
      spawnProcess: () =>
        fakeSyncChild({
          stderrChunks: splitUtf8(stderr, "诊", 2),
          stdout: JSON.stringify(completedResult()),
        }),
    }),
  );

  assert.equal(completion.stderr, stderr);
  assert.deepEqual(phases, ["pulling"]);
});

test("runSyncProcess waits for close and both output streams before settling", async () => {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  let settled = false;

  const completionPromise = runSyncProcess(
    processOptions({
      spawnProcess: () => child,
    }),
  ).finally(() => {
    settled = true;
  });

  child.emit("close", 0);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(settled, false);

  child.stdout.end(JSON.stringify(completedResult()));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(settled, false);

  child.stderr.end();
  const completion = await completionPromise;
  assert.equal(completion.result.outcome, "completed");
});

test("runSyncProcess rejects stdout and stderr stream errors once when end and close follow", async (t) => {
  for (const streamName of ["stdout", "stderr"]) {
    await t.test(streamName, async () => {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child[streamName].on("error", () => undefined);
      let rejectionCount = 0;

      const completion = runSyncProcess(
        processOptions({
          spawnProcess: () => child,
        }),
      ).catch((error) => {
        rejectionCount += 1;
        throw error;
      });

      child[streamName].emit("error", new Error(`${streamName} stream failed`));
      child.stdout.end(JSON.stringify(completedResult()));
      child.stderr.end();
      child.emit("close", 0);

      await assert.rejects(completion, { message: `${streamName} stream failed` });
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(rejectionCount, 1);
    });
  }
});

test("runSyncProcess resolves a structured conflict result with exit code 2", async () => {
  const completion = await runSyncProcess(
    processOptions({
      spawnProcess: () =>
        fakeSyncChild({
          stdout: JSON.stringify(conflictResult()),
          exitCode: 2,
        }),
    }),
  );

  assert.equal(completion.exitCode, 2);
  assert.equal(completion.result.outcome, "conflict");
});

test("runSyncProcess rejects malformed success output with the strict parser error", async () => {
  await assert.rejects(
    runSyncProcess(
      processOptions({
        spawnProcess: () => fakeSyncChild({ stdout: "{}", exitCode: 0 }),
      }),
    ),
    /Invalid Codex sync result/,
  );
});

test("runSyncProcess rejects nonzero malformed results using stderr, stdout, then exit code", async (t) => {
  await t.test("stderr", async () => {
    await assert.rejects(
      runSyncProcess(
        processOptions({
          spawnProcess: () => fakeSyncChild({ stderrChunks: [" permission denied \n"], stdout: "{}", exitCode: 1 }),
        }),
      ),
      { message: "permission denied" },
    );
  });

  await t.test("stdout", async () => {
    await assert.rejects(
      runSyncProcess(
        processOptions({
          spawnProcess: () => fakeSyncChild({ stdout: " malformed output \n", exitCode: 1 }),
        }),
      ),
      { message: "malformed output" },
    );
  });

  await t.test("exit code", async () => {
    await assert.rejects(
      runSyncProcess(
        processOptions({
          spawnProcess: () => fakeSyncChild({ exitCode: 7 }),
        }),
      ),
      { message: "codex-usage exited with code 7" },
    );
  });
});

test("runSyncProcess strictly rejects unsafe integers on a nonzero exit", async () => {
  const unsafeResult = JSON.stringify(conflictResult()).replace(
    '"discovered":1',
    '"discovered":9007199254740993',
  );

  await assert.rejects(
    runSyncProcess(
      processOptions({
        spawnProcess: () => fakeSyncChild({ stdout: unsafeResult, exitCode: 2 }),
      }),
    ),
  );
});

test("runSyncProcess reports ENOENT once even if close follows the child error", async () => {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  let spawnCount = 0;
  let rejectionCount = 0;

  const completion = runSyncProcess(
    processOptions({
      spawnProcess: () => {
        spawnCount += 1;
        return child;
      },
    }),
  ).catch((error) => {
    rejectionCount += 1;
    throw error;
  });

  const error = new Error("spawn failed");
  error.code = "ENOENT";
  child.emit("error", error);
  child.stdout.end(JSON.stringify(completedResult()));
  child.stderr.end();
  child.emit("close", 0);

  await assert.rejects(completion, /Could not start bundled codex-usage executable: \/bin\/codex-usage/);
  assert.equal(spawnCount, 1);
  assert.equal(rejectionCount, 1);
});

test("extension sync orchestration uses one inventory-backed task picker contract", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const coreSource = fs.readFileSync(path.join(__dirname, "../src/core.ts"), "utf8");

  for (const removedName of [
    "resolveSyncThreadIds",
    "resolvedSyncOptions",
    "SyncImportCommandOptions",
    "buildSyncExportArgs",
    "buildSyncImportArgs",
    "appendSyncArgs",
  ]) {
    assert.doesNotMatch(extensionSource, new RegExp(`\\b${removedName}\\b`));
    assert.doesNotMatch(coreSource, new RegExp(`\\b${removedName}\\b`));
  }
  assert.doesNotMatch(extensionSource, /selectSyncProjectSettings|selectSyncThreadSettings|conversationMode/);
  assert.match(extensionSource, /buildSyncInventoryArgs/);
  assert.match(extensionSource, /parseSyncInventory/);
  assert.match(extensionSource, /createQuickPick/);
  assert.match(extensionSource, /SYNC_SELECTION_VERSION_STATE_KEY/);
  assert.match(extensionSource, /selectionVersion:\s*readSyncSelectionVersionState/);
  assert.doesNotMatch(extensionSource, /projectKeys:\s*settings\.sync/);

  assert.equal((extensionSource.match(/registerCommand\("codexUsage\.selectSyncTasks"/g) || []).length, 1);
  assert.doesNotMatch(extensionSource, /registerCommand\("codexUsage\.selectSync(?:Projects|Threads)"/);
});

test("routine sync and status validate schema-v2 task selection before spawning", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const runSyncSource = extensionSource.slice(
    extensionSource.indexOf("async function runSyncNow"),
    extensionSource.indexOf("async function showSyncStatus"),
  );
  const statusSource = extensionSource.slice(
    extensionSource.indexOf("async function showSyncStatus"),
    extensionSource.indexOf("async function openSyncFolder"),
  );

  const runGuard = runSyncSource.indexOf("if (!hasValidSyncSelection(settings.sync))");
  const runSpawn = runSyncSource.indexOf("runSyncProcess(");
  assert.ok(runGuard >= 0 && runGuard < runSpawn);
  assert.match(runSyncSource.slice(runGuard, runSpawn), /return false;/);
  assert.equal((runSyncSource.match(/runSyncProcess\(/g) || []).length, 1);
  assert.doesNotMatch(runSyncSource, /buildSyncInventoryArgs|parseSyncInventory|runCodexUsage\(/);
  assert.doesNotMatch(runSyncSource, /buildThreadsArgs|sync\", \"status|sync\", \"import|sync\", \"export/);
  assert.match(
    runSyncSource,
    /outcomeStatus \?\? \(message\.toLowerCase\(\)\.includes\("conflict"\) \? "conflict" : "issue"\)/,
  );

  const statusGuard = statusSource.indexOf("if (!hasValidSyncSelection(settings.sync))");
  const statusSpawn = statusSource.indexOf("runCodexUsage(");
  assert.ok(statusGuard >= 0 && statusGuard < statusSpawn);
  assert.match(statusSource.slice(statusGuard, statusSpawn), /return;/);
  assert.equal((statusSource.match(/runCodexUsage\(/g) || []).length, 1);
  assert.equal((statusSource.match(/buildSyncStatusArgs\(/g) || []).length, 1);
  assert.doesNotMatch(statusSource, /buildSyncInventoryArgs|parseSyncInventory|buildThreadsArgs|runSyncProcess/);

  for (const commandSource of [runSyncSource, statusSource]) {
    assert.match(commandSource, /threadIds:\s*settings\.sync\.threadIds/);
    assert.doesNotMatch(commandSource, /projectKeys|conversationMode/);
    assert.match(commandSource, /autoTransitions: settings\.projectTransitions\.autoDetect/);
  }
});

test("folder and exact task setup commits only after picker acceptance", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const selectionSource = extensionSource.slice(
    extensionSource.indexOf("async function selectSyncTaskSettings"),
    extensionSource.indexOf("async function configureSync"),
  );
  const configureSource = extensionSource.slice(
    extensionSource.indexOf("async function configureSync"),
    extensionSource.indexOf("async function showSyncMenu"),
  );
  const changeFolderSource = extensionSource.slice(
    extensionSource.indexOf("async function changeSyncFolder"),
    extensionSource.indexOf("async function clearSyncSetup"),
  );

  assert.match(selectionSource, /buildSyncInventoryArgs\(\{\s*syncDir,/);
  assert.match(selectionSource, /const inventory = parseSyncInventory\(result\.stdout\)/);
  assert.match(selectionSource, /buildTaskPickerItems\(inventory, settings\.sync\.threadIds\)/);
  assert.match(selectionSource, /showSyncTaskPicker\(rows, settings\.sync\.threadIds\)/);

  const inventoryRun = selectionSource.indexOf("runCodexUsage(");
  const selectionGuard = selectionSource.indexOf("if (!selectedThreadIds)");
  const enabledWrite = selectionSource.indexOf('"sync.enabled"');
  const stateWrites = [...selectionSource.matchAll(/context\.globalState\.update\(/g)].map((match) => match.index);
  assert.ok(inventoryRun >= 0 && inventoryRun < selectionGuard);
  assert.ok(enabledWrite > selectionGuard);
  assert.equal(stateWrites.length, 3);
  assert.ok(stateWrites.every((index) => index > selectionGuard));
  assert.match(selectionSource.slice(selectionGuard, stateWrites[0]), /return false;/);
  assert.match(selectionSource, /globalState\.update\(SYNC_DIR_STATE_KEY, syncDir\)/);
  assert.match(selectionSource, /globalState\.update\(SYNC_THREAD_IDS_STATE_KEY, selectedThreadIds\)/);
  assert.match(selectionSource, /globalState\.update\(SYNC_SELECTION_VERSION_STATE_KEY, SYNC_SELECTION_VERSION\)/);

  assert.ok(configureSource.indexOf("pickSyncFolder(") < configureSource.indexOf("selectSyncTaskSettings("));
  assert.ok(changeFolderSource.indexOf("pickSyncFolder(") < changeFolderSource.indexOf("selectSyncTaskSettings("));
});

test("task picker adapter canonicalizes hierarchical selections and settles once", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const pickerSource = extensionSource.slice(
    extensionSource.indexOf("function showSyncTaskPicker"),
    extensionSource.indexOf("async function selectSyncTaskSettings"),
  );

  assert.match(pickerSource, /createQuickPick<TaskQuickPickItem>\(\)/);
  assert.match(pickerSource, /canSelectMany = true/);
  assert.match(pickerSource, /kind:\s*vscode\.QuickPickItemKind\.Separator/);
  assert.doesNotMatch(pickerSource, /\.\.\.row/);
  assert.ok(
    pickerSource.indexOf("reduceTaskSelection(selectedThreadIds, removed") <
      pickerSource.indexOf("reduceTaskSelection(selectedThreadIds, added"),
  );
  assert.match(pickerSource, /selectedPickerItemIds\(rows, selectedThreadIds\)/);
  assert.match(pickerSource, /Select at least one Codex task/);
  assert.match(pickerSource, /let settled = false/);
});

test("status badge and tooltip prefer setup required for disabled invalid selection", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const badgeSource = extensionSource.slice(
    extensionSource.indexOf("function syncStatusBadge"),
    extensionSource.indexOf("function syncStatusTooltip"),
  );
  const tooltipSource = extensionSource.slice(
    extensionSource.indexOf("function syncStatusTooltip"),
    extensionSource.indexOf("async function syncOnFocus"),
  );

  for (const statusSource of [badgeSource, tooltipSource]) {
    const validityGuard = statusSource.indexOf("if (!hasValidSyncSelection(settings.sync))");
    const enabledGuard = statusSource.indexOf("if (!settings.sync.enabled)");
    assert.ok(validityGuard >= 0 && validityGuard < enabledGuard);
  }
  assert.match(badgeSource, /return "Sync: Setup required";/);
  assert.match(tooltipSource, /return "Sync: Setup required\. Select a folder and at least one Codex task\.";/);
});

test("clear and migration retain only the deprecated folder migration contract", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const clearSource = extensionSource.slice(
    extensionSource.indexOf("async function clearSyncSetup"),
    extensionSource.indexOf("async function refreshSyncUi"),
  );
  const migrationSource = extensionSource.slice(
    extensionSource.indexOf("async function migrateDeprecatedSyncSettings"),
    extensionSource.indexOf("function readSettings"),
  );

  const versionClear = clearSource.indexOf("globalState.update(SYNC_SELECTION_VERSION_STATE_KEY, 0)");
  const folderClear = clearSource.indexOf("globalState.update(SYNC_DIR_STATE_KEY, undefined)");
  const idsClear = clearSource.indexOf("globalState.update(SYNC_THREAD_IDS_STATE_KEY, undefined)");
  assert.ok(versionClear >= 0 && versionClear < folderClear && folderClear < idsClear);
  assert.doesNotMatch(clearSource, /SYNC_PROJECT_KEYS_STATE_KEY|SYNC_CONVERSATION_MODE_STATE_KEY/);

  assert.match(migrationSource, /config\.get<string>\("sync\.dir", ""\)/);
  assert.equal(
    (migrationSource.match(/globalState\.update\(SYNC_DIR_STATE_KEY, legacyDir\.trim\(\)\)/g) || []).length,
    1,
  );
  assert.doesNotMatch(migrationSource, /sync\.threadIds|sync\.projectKeys|sync\.conversationMode/);
});
