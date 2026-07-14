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

function fakeSyncChild({ stderrChunks = [], stdout = "", exitCode = 0 }) {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  queueMicrotask(() => {
    for (const chunk of stderrChunks) {
      child.stderr.write(chunk);
    }
    child.stdout.end(stdout);
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

test("extension sync orchestration has no resolver or legacy three-command path", () => {
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

  const runSyncSource = extensionSource.slice(
    extensionSource.indexOf("async function runSyncNow"),
    extensionSource.indexOf("async function showSyncStatus"),
  );
  const statusSource = extensionSource.slice(
    extensionSource.indexOf("async function showSyncStatus"),
    extensionSource.indexOf("async function openSyncFolder"),
  );
  assert.equal((runSyncSource.match(/runSyncProcess\(/g) || []).length, 1);
  assert.doesNotMatch(runSyncSource, /buildThreadsArgs|sync\", \"status|sync\", \"import|sync\", \"export/);
  assert.match(
    runSyncSource,
    /outcomeStatus \?\? \(message\.toLowerCase\(\)\.includes\("conflict"\) \? "conflict" : "issue"\)/,
  );
  assert.equal((statusSource.match(/runCodexUsage\(/g) || []).length, 1);
  assert.equal((statusSource.match(/buildSyncStatusArgs\(/g) || []).length, 1);
  assert.doesNotMatch(statusSource, /buildThreadsArgs|runSyncProcess/);
  assert.equal((extensionSource.match(/buildThreadsArgs\(/g) || []).length, 2);

  for (const commandSource of [runSyncSource, statusSource]) {
    assert.match(commandSource, /conversationMode === "allInProjects"\s*\? settings\.sync\.projectKeys\s*:\s*\[\]/);
    assert.match(commandSource, /conversationMode === "selectedConversations"\s*\? settings\.sync\.threadIds\s*:\s*\[\]/);
    assert.match(commandSource, /autoTransitions: settings\.projectTransitions\.autoDetect/);
  }
});
