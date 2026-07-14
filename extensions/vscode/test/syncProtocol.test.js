const assert = require("node:assert/strict");
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

test("buildSyncRunArgs passes projects directly without resolving threads", () => {
  assert.deepEqual(
    buildSyncRunArgs({ syncDir: "/sync", projectKeys: ["repo-a"], threadIds: [], autoTransitions: false }),
    ["sync", "run", "--json", "--sync-dir", "/sync", "--no-auto-transitions", "--project-key", "repo-a"],
  );
});

test("sync argument builders normalize repeatable selectors and preserve JSON flag position", () => {
  const options = {
    syncDir: " /sync ",
    projectKeys: [" repo-a ", "", "repo-a", "repo-b"],
    threadIds: [" thread-1 ", "thread-1", "thread-2"],
    autoTransitions: true,
  };

  assert.deepEqual(buildSyncRunArgs(options), [
    "sync",
    "run",
    "--json",
    "--sync-dir",
    "/sync",
    "--project-key",
    "repo-a",
    "--project-key",
    "repo-b",
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
    "--project-key",
    "repo-a",
    "--project-key",
    "repo-b",
    "--thread-id",
    "thread-1",
    "--thread-id",
    "thread-2",
  ]);
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
  assert.match(summary.message, /2 conversations/);
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
