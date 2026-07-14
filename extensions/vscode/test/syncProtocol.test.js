const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  buildSyncRunArgs,
  buildSyncStatusArgs,
  parseSyncProgressLine,
  parseSyncRunResult,
  parseSyncStatusSummary,
} = require("../out/syncProtocol");

function syncThread(overrides = {}) {
  return {
    thread_id: "thread-1",
    state: "local_ahead",
    action: "push",
    reason: "local conversation changed",
    local_path: "/codex/thread-1.jsonl",
    remote_path: "/sync/conversations/thread-1.jsonl",
    local_sha256: "local-hash",
    remote_sha256: "remote-hash",
    base_sha256: "base-hash",
    updated_at: "2026-07-14T12:00:00+00:00",
    source_relative_path: "2026/07/14/thread-1.jsonl",
    project_key: "repo-a",
    project_label: "Repo A",
    memory_database_rows: 0,
    ...overrides,
  };
}

function syncIssue(overrides = {}) {
  return {
    code: "concurrent_local_change",
    message: "Local conversation changed during sync.",
    thread_id: "thread-1",
    ...overrides,
  };
}

function syncResult(outcome = "completed", overrides = {}) {
  return {
    outcome,
    counts: {
      discovered: 1,
      selected: 1,
      remote: 0,
      pulled: 0,
      pushed: 1,
      unchanged: 0,
      conflicts: 0,
      issues: 0,
    },
    timings_ms: { discovery: 1, planning: 2, pull: 0, push: 3, index: 1, total: 7 },
    threads: [syncThread()],
    pulled: [],
    pushed: ["thread-1"],
    issues: [],
    ...overrides,
  };
}

test("buildSyncRunArgs passes exact task ids without project selectors", () => {
  assert.deepEqual(
    buildSyncRunArgs({ syncDir: "/sync", threadIds: ["thread-1"], autoTransitions: false }),
    ["sync", "run", "--json", "--sync-dir", "/sync", "--no-auto-transitions", "--thread-id", "thread-1"],
  );
});

test("sync argument builders normalize repeatable selectors and preserve JSON flag position", () => {
  const options = {
    syncDir: " /sync ",
    threadIds: [" thread-1 ", "thread-1", "thread-2"],
    autoTransitions: true,
  };

  assert.deepEqual(buildSyncRunArgs(options), [
    "sync",
    "run",
    "--json",
    "--sync-dir",
    "/sync",
    "--thread-id",
    "thread-1",
    "--thread-id",
    "thread-2",
  ]);
  assert.deepEqual(buildSyncStatusArgs(options), [
    "sync",
    "status",
    "--json",
    "--sync-dir",
    "/sync",
    "--thread-id",
    "thread-1",
    "--thread-id",
    "thread-2",
  ]);
  assert.doesNotMatch(buildSyncRunArgs(options).join(" "), /--project-key/);
  assert.doesNotMatch(buildSyncStatusArgs(options).join(" "), /--project-key/);
});

test("sync command options expose only the exact task selector contract", () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/syncProtocol.ts"), "utf8");
  const optionsContract = source.slice(
    source.indexOf("export type SyncCommandOptions"),
    source.indexOf("export type SyncProgressPhase"),
  );

  assert.match(optionsContract, /syncDir:\s*string/);
  assert.match(optionsContract, /threadIds:\s*string\[\]/);
  assert.match(optionsContract, /autoTransitions:\s*boolean/);
  assert.doesNotMatch(optionsContract, /projectKeys/);
  assert.doesNotMatch(source, /--project-key/);
});

test("parseSyncProgressLine accepts only typed phase events", () => {
  for (const phase of ["scanning", "pulling", "pushing"]) {
    assert.deepEqual(parseSyncProgressLine(JSON.stringify({ type: "sync_progress", phase })), {
      type: "sync_progress",
      phase,
    });
  }

  for (const line of [
    "cache refreshed",
    "{",
    "null",
    "[]",
    '{"type":"other","phase":"pulling"}',
    '{"type":"sync_progress","phase":"unknown"}',
  ]) {
    assert.equal(parseSyncProgressLine(line), undefined);
  }
});

test("parseSyncRunResult preserves completed conflict and issue outcomes", () => {
  const completed = syncResult();
  const conflict = syncResult("conflict", {
    counts: { ...completed.counts, pushed: 0, conflicts: 1 },
    threads: [syncThread({ state: "conflict", action: "conflict" })],
    pushed: [],
  });
  const issue = syncResult("issue", {
    counts: { ...completed.counts, pushed: 0, issues: 1 },
    threads: [syncThread({ state: "issue", action: "issue" })],
    pushed: [],
    issues: [syncIssue()],
  });

  assert.deepEqual(parseSyncRunResult(JSON.stringify(completed)), completed);
  assert.deepEqual(parseSyncRunResult(JSON.stringify(conflict)), conflict);
  assert.deepEqual(parseSyncRunResult(JSON.stringify(issue)), issue);
});

test("parseSyncRunResult rejects malformed top-level and nested result fields", () => {
  const valid = syncResult();
  const malformedResults = [
    "{",
    "null",
    JSON.stringify({ ...valid, outcome: "success" }),
    JSON.stringify({ ...valid, counts: { ...valid.counts, pushed: "1" } }),
    JSON.stringify({ ...valid, timings_ms: { ...valid.timings_ms, total: -1 } }),
    JSON.stringify({ ...valid, threads: [{ ...valid.threads[0], thread_id: 7 }] }),
    JSON.stringify({ ...valid, pulled: [7] }),
    JSON.stringify({ ...valid, issues: [{ ...syncIssue(), message: null }] }),
  ];

  for (const payload of malformedResults) {
    assert.throws(() => parseSyncRunResult(payload), /Codex sync result/);
  }
});

test("parseSyncRunResult requires every v2 result structure", () => {
  const requiredFields = ["outcome", "counts", "timings_ms", "threads", "pulled", "pushed", "issues"];
  for (const field of requiredFields) {
    const payload = syncResult();
    delete payload[field];
    assert.throws(() => parseSyncRunResult(JSON.stringify(payload)), /Codex sync result/);
  }
});

test("parseSyncRunResult rejects an unsafe count integer", () => {
  const payload = JSON.stringify(syncResult()).replace('"discovered":1', '"discovered":9007199254740993');

  assert.throws(() => parseSyncRunResult(payload), /counts\.discovered/);
});

test("parseSyncRunResult rejects an unsafe timing integer", () => {
  const payload = JSON.stringify(syncResult()).replace('"discovery":1', '"discovery":9007199254740993');

  assert.throws(() => parseSyncRunResult(payload), /timings_ms\.discovery/);
});

test("parseSyncRunResult rejects unsafe thread memory database rows", () => {
  const payload = JSON.stringify(syncResult()).replace(
    '"memory_database_rows":0',
    '"memory_database_rows":9007199254740993',
  );

  assert.throws(() => parseSyncRunResult(payload), /threads\[0\]\.memory_database_rows/);
});

test("parseSyncRunResult accepts Number.MAX_SAFE_INTEGER in numeric fields", () => {
  const payload = syncResult();
  payload.counts.discovered = Number.MAX_SAFE_INTEGER;
  payload.timings_ms.discovery = Number.MAX_SAFE_INTEGER;
  payload.threads[0].memory_database_rows = Number.MAX_SAFE_INTEGER;

  assert.deepEqual(parseSyncRunResult(JSON.stringify(payload)), payload);
});

test("parseSyncStatusSummary counts states and memory warnings", () => {
  const summary = parseSyncStatusSummary(
    JSON.stringify({
      threads: [
        { thread_id: "t1", state: "synced", memory_database_rows: 0 },
        { thread_id: "t2", state: "conflict", memory_database_rows: 2 },
      ],
    }),
  );

  assert.equal(summary.total, 2);
  assert.equal(summary.synced, 1);
  assert.equal(summary.conflicts, 1);
  assert.equal(summary.memoryWarnings, 1);
  assert.equal(summary.localChanges, 0);
  assert.equal(summary.remoteChanges, 0);
  assert.equal(summary.fastForwards, 0);
  assert.equal(summary.issues, 0);
  assert.match(summary.message, /2 tasks/);
  assert.match(summary.message, /1 synced/);
  assert.match(summary.message, /1 conflict/);
});

test("parseSyncStatusSummary describes planned pull push and fast-forward states", () => {
  const summary = parseSyncStatusSummary(
    JSON.stringify({
      threads: [
        { thread_id: "a", state: "local_ahead" },
        { thread_id: "b", state: "remote_ahead" },
        { thread_id: "c", state: "fast_forward_push" },
        { thread_id: "d", state: "fast_forward_pull" },
        { thread_id: "e", state: "synced" },
      ],
    }),
  );

  assert.equal(summary.total, 5);
  assert.equal(summary.synced, 1);
  assert.match(summary.message, /1 local change/);
  assert.match(summary.message, /1 remote change/);
  assert.match(summary.message, /2 fast-forward/);
});

test("parseSyncStatusSummary counts valid plan issues and retains the first actionable message", () => {
  const summary = parseSyncStatusSummary(
    JSON.stringify({
      threads: [{ thread_id: "t1", state: "issue" }, null, "malformed row"],
      issues: [
        { code: "empty_message", message: "", thread_id: "t1" },
        null,
        { code: "missing_remote_file", message: " Remote conversation file is missing. ", thread_id: "t1" },
        { code: "later", message: "Later issue", thread_id: "t2" },
      ],
    }),
  );

  assert.equal(summary.issues, 3);
  assert.match(summary.message, /3 issues/);
  assert.match(summary.message, /Remote conversation file is missing\./);
  assert.doesNotMatch(summary.message, /Later issue/);
});

test("parseSyncStatusSummary rejects malformed top-level JSON but tolerates malformed collections", () => {
  assert.throws(() => parseSyncStatusSummary("{"), /Could not parse Codex sync status JSON/);
  assert.doesNotThrow(() => parseSyncStatusSummary(JSON.stringify({ threads: null, issues: [7, {}] })));
});
