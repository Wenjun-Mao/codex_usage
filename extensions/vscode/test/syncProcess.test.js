const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { PassThrough } = require("node:stream");
const test = require("node:test");

const { cacheDbPath, legacyCacheDbPaths } = require("../out/core");
const {
  dashboardLoadingKind,
  executeDashboardRefresh,
  publishDashboardRefresh,
} = require("../out/dashboardRefresh");
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

test("dashboard loading kind distinguishes new, legacy, and schema-8 cache storage", async (t) => {
  const storagePath = fs.mkdtempSync(path.join(__dirname, "dashboard-cache-"));
  t.after(() => fs.rmSync(storagePath, { recursive: true, force: true }));

  assert.equal(await dashboardLoadingKind(storagePath), "initializing");
  fs.mkdirSync(path.dirname(legacyCacheDbPaths(storagePath)[1]), { recursive: true });
  fs.writeFileSync(legacyCacheDbPaths(storagePath)[1], "legacy");
  assert.equal(await dashboardLoadingKind(storagePath), "rebuilding");
  fs.writeFileSync(cacheDbPath(storagePath), "schema-8");
  assert.equal(await dashboardLoadingKind(storagePath), "refreshing");
});

test("dashboard execution passes timing output and preserves a report when the sidecar is unavailable", async (t) => {
  const storagePath = fs.mkdtempSync(path.join(__dirname, "dashboard-timing-"));
  t.after(() => fs.rmSync(storagePath, { recursive: true, force: true }));
  const reportPath = path.join(storagePath, "report-1.html");
  const timingOutputPath = path.join(storagePath, "report-1.timing.json");
  const output = [];
  const panel = { webview: { html: "", cspSource: "vscode-resource:" } };
  const request = {
    requestId: 1,
    panel,
    settings: {
      range: "today",
      projectKeys: [],
      theme: "auto",
      taskTransfer: { folder: "" },
      projectTransitions: { autoDetect: true },
    },
    versionLabel: "v1.0.0",
    reportViewState: { current: "usage" },
    reportPath,
    timingOutputPath,
  };
  const result = await executeDashboardRefresh(request, {
    globalStoragePath: storagePath,
    resolveExecutable: async () => "/bin/codex-usage",
    runCodexUsage: async (_executablePath, args) => {
      assert.deepEqual(args, [
        "report", "--range", "today", "--output", reportPath,
        "--theme", "auto", "--timing-output", timingOutputPath,
      ]);
      await fs.promises.writeFile(reportPath, "<html><head></head><body><main>Report</main></body></html>");
      return { stdout: "", stderr: "" };
    },
    appendOutput: (line) => output.push(line),
    setStatus: () => undefined,
  });

  assert.equal(result.kind, "success");
  assert.match(result.html, /Report/);
  assert.equal(Number.isFinite(result.elapsedSeconds), true);
  assert.match(panel.webview.html, /Initializing Codex usage cache/);
  assert.deepEqual(output, []);
  assert.match(result.warnings.join("\n"), /timing sidecar unavailable/i);
  publishDashboardRefresh(request, result, {
    appendOutput: (line) => output.push(line),
    updateStatus: () => undefined,
    showError: () => undefined,
  }, {
    isCurrent: () => true,
    commit: (sideEffect) => {
      sideEffect();
      return true;
    },
  });
  assert.match(output.join("\n"), /timing sidecar unavailable/i);
});

test("extension delegates Task Transfer commands without retaining task choices", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");

  assert.match(extensionSource, /new TaskTransferController\(\s*taskTransferPort,?\s*\)/);
  assert.match(extensionSource, /createTaskTransferVscodePort\(context/);
  assert.equal((extensionSource.match(/registerCommand\("codexUsage\.selectSyncTasks"/g) || []).length, 1);
  assert.match(extensionSource, /"codexUsage\.selectSyncTasks", \(\) => taskTransfer\.showMenu\(\)/);
  assert.doesNotMatch(extensionSource, /transientThreadIds|syncThreadIds|selectionVersion/);
  assert.doesNotMatch(extensionSource, /syncSetupTransaction|SyncSetupMutationCoordinator/);
  assert.doesNotMatch(extensionSource, /TaskTransferController\([\s\S]{0,160}projectTransitions\.autoDetect/);
});

test("sync has no automatic focus activation or file watcher trigger", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");

  assert.match(extensionSource, /registerCommand\("codexUsage\.pullTasks"/);
  assert.match(extensionSource, /registerCommand\("codexUsage\.pushTasks"/);
  assert.doesNotMatch(extensionSource, /codexUsage\.syncNow/);
  assert.doesNotMatch(extensionSource, /onDidChangeWindowState/);
  assert.doesNotMatch(extensionSource, /createFileSystemWatcher/);
  assert.doesNotMatch(extensionSource, /syncOnFocus|configureSyncWatcher|auto sync/);
});

test("task picker adapter renders staged scoped transfers and settles once", () => {
  const pickerSource = fs.readFileSync(
    path.join(__dirname, "../src/taskTransferVscodePicker.ts"),
    "utf8",
  );

  assert.match(pickerSource, /createQuickPick<TaskQuickPickItem>\(\)/);
  assert.match(pickerSource, /quickPick\.canSelectMany = isTaskStep/);
  assert.match(pickerSource, /QuickInputButtons\.Back/);
  assert.match(pickerSource, /visibleTaskPickerItems\(rows, state, operation\)/);
  assert.match(pickerSource, /Select at least one Codex task to import/);
  assert.match(pickerSource, /Select at least one Codex task to export/);
  assert.match(pickerSource, /let settled = false/);
});

test("extension status text uses only pure transient Task Transfer labels", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  const statusSource = extensionSource.slice(
    extensionSource.indexOf("function updateStatusItem"),
    extensionSource.indexOf("function themeLabel"),
  );

  assert.match(statusSource, /`Codex Usage: \$\{settings\.range\}`/);
  assert.match(statusSource, /const usageText = projectCount > 0/);
  assert.match(statusSource, /transientStatusLabel\(transientStatus\)/);
  assert.match(statusSource, /statusItem\.text = transientStatus/);
  assert.doesNotMatch(statusSource, /Setup|required|Sync:|enabled|threadIds|taskTransfer\.folder/i);
});

test("activation delegates obsolete state cleanup to the VS Code state adapter", () => {
  const extensionSource = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");

  assert.match(extensionSource, /await migrateVscodeTaskTransferState\(/);
  assert.doesNotMatch(extensionSource, /sync\.enabled|ConfigurationTarget\.WorkspaceFolder/);
  assert.doesNotMatch(extensionSource, /syncSetupTransaction|SyncSetupMutationCoordinator/);
});
