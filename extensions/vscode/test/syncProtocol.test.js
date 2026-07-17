const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  buildSyncPullArgs,
  buildSyncPushArgs,
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
    reason: "local task changed",
    local_path: "/codex/thread-1.jsonl",
    remote_path: "/sync/tasks/thread-1.jsonl",
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
    message: "Local task changed during transfer.",
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

test("directional sync builders pass exact task ids without project selectors", () => {
  assert.deepEqual(
    buildSyncPullArgs({
      syncDir: "/sync",
      threadIds: ["thread-1"],
      autoTransitions: false,
      candidateProjectRoots: [],
      projectBindings: [],
    }),
    ["sync", "pull", "--json", "--sync-dir", "/sync", "--no-auto-transitions", "--thread-id", "thread-1"],
  );
  assert.deepEqual(
    buildSyncPushArgs({
      syncDir: "/sync",
      threadIds: ["thread-1"],
      autoTransitions: false,
      candidateProjectRoots: [],
      projectBindings: [],
    }),
    ["sync", "push", "--json", "--sync-dir", "/sync", "--no-auto-transitions", "--thread-id", "thread-1"],
  );
});

test("sync argument builders normalize repeatable selectors and preserve JSON flag position", () => {
  const options = {
    syncDir: " /sync ",
    threadIds: [" thread-1 ", "thread-1", "thread-2"],
    autoTransitions: true,
    candidateProjectRoots: [],
    projectBindings: [],
  };

  assert.deepEqual(buildSyncPullArgs(options), [
    "sync",
    "pull",
    "--json",
    "--sync-dir",
    "/sync",
    "--thread-id",
    "thread-1",
    "--thread-id",
    "thread-2",
  ]);
  assert.deepEqual(buildSyncPushArgs(options), [
    "sync",
    "push",
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
  assert.doesNotMatch(buildSyncPullArgs(options).join(" "), /--project-key/);
  assert.doesNotMatch(buildSyncPushArgs(options).join(" "), /--project-key/);
  assert.doesNotMatch(buildSyncStatusArgs(options).join(" "), /--project-key/);
});

test("sync command options expose the transient project resolution contract", () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/syncProtocol.ts"), "utf8");
  const optionsContract = source.slice(
    source.indexOf("export type SyncCommandOptions"),
    source.indexOf("export type SyncProgressPhase"),
  );

  assert.match(optionsContract, /syncDir:\s*string/);
  assert.match(optionsContract, /threadIds:\s*string\[\]/);
  assert.match(optionsContract, /autoTransitions:\s*boolean/);
  assert.match(optionsContract, /candidateProjectRoots:\s*string\[\]/);
  assert.match(optionsContract, /projectBindings:\s*ProjectBinding\[\]/);
  assert.doesNotMatch(optionsContract, /projectKeys/);
  assert.doesNotMatch(source, /--project-key/);
});

test("import args preserve Windows paths and repository keys as separate argv values", () => {
  assert.deepEqual(
    buildSyncPullArgs({
      syncDir: "C:\\Transfer",
      threadIds: ["task-1"],
      autoTransitions: true,
      candidateProjectRoots: ["C:\\Code\\repo"],
      projectBindings: [
        {
          projectKey: "https://github.com/example/repo",
          path: "C:\\Code\\repo",
          confirmedUnverified: false,
        },
        {
          projectKey: "c:/source/plain",
          path: "D:\\Code\\plain",
          confirmedUnverified: true,
        },
      ],
    }),
    [
      "sync", "pull", "--json", "--sync-dir", "C:\\Transfer",
      "--candidate-project-root", "C:\\Code\\repo",
      "--project-binding", "https://github.com/example/repo", "C:\\Code\\repo",
      "--project-binding", "c:/source/plain", "D:\\Code\\plain",
      "--confirm-unverified-project", "c:/source/plain",
      "--thread-id", "task-1",
    ],
  );
});

test("export and status args append roots and only explicitly supplied bindings", () => {
  const options = {
    syncDir: "/transfer",
    threadIds: ["task-1"],
    autoTransitions: true,
    candidateProjectRoots: ["/code/repo"],
    projectBindings: [
      {
        projectKey: "/source/plain",
        path: "/code/repo",
        confirmedUnverified: true,
      },
    ],
  };
  const suffix = [
    "--sync-dir", "/transfer",
    "--candidate-project-root", "/code/repo",
    "--project-binding", "/source/plain", "/code/repo",
    "--confirm-unverified-project", "/source/plain",
    "--thread-id", "task-1",
  ];

  assert.deepEqual(buildSyncPushArgs(options), ["sync", "push", "--json", ...suffix]);
  assert.deepEqual(buildSyncStatusArgs(options), ["sync", "status", "--json", ...suffix]);
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

test("parseSyncRunResult requires every task transfer result structure", () => {
  const requiredFields = ["outcome", "counts", "timings_ms", "threads", "pulled", "pushed", "issues"];
  for (const field of requiredFields) {
    const payload = syncResult();
    delete payload[field];
    assert.throws(
      () => parseSyncRunResult(JSON.stringify(payload)),
      /task transfer payload contract/,
    );
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
        syncThread({ thread_id: "t1", state: "synced", action: "none" }),
        syncThread({ thread_id: "t2", state: "conflict", action: "conflict", memory_database_rows: 2 }),
      ],
      issues: [],
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
        syncThread({ thread_id: "a", state: "local_ahead", action: "push" }),
        syncThread({ thread_id: "b", state: "remote_ahead", action: "pull" }),
        syncThread({ thread_id: "c", state: "fast_forward_push", action: "push" }),
        syncThread({ thread_id: "d", state: "fast_forward_pull", action: "pull" }),
        syncThread({ thread_id: "e", state: "synced", action: "none" }),
      ],
      issues: [],
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
      threads: [syncThread({ thread_id: "t1", state: "issue", action: "issue" })],
      issues: [
        { code: "empty_message", message: "", thread_id: "t1" },
        { code: "missing_remote_file", message: " Remote task file is missing. ", thread_id: "t1" },
        { code: "later", message: "Later issue", thread_id: "t2" },
      ],
    }),
  );

  assert.equal(summary.issues, 3);
  assert.match(summary.message, /3 issues/);
  assert.match(summary.message, /Remote task file is missing\./);
  assert.doesNotMatch(summary.message, /Later issue/);
});

test("parseSyncStatusSummary requires exact top-level status collections", () => {
  assert.throws(() => parseSyncStatusSummary("{"), /Could not parse Codex sync status JSON/);
  for (const payload of [
    null,
    [],
    {},
    { threads: [] },
    { issues: [] },
    { threads: null, issues: [] },
    { threads: [], issues: null },
    { threads: [], issues: [], unexpected: true },
  ]) {
    assert.throws(
      () => parseSyncStatusSummary(JSON.stringify(payload)),
      /Invalid Codex sync status/,
    );
  }
});

test("parseSyncStatusSummary rejects malformed task and issue records", () => {
  const missingTaskField = syncThread();
  delete missingTaskField.reason;
  const extraTaskField = { ...syncThread(), unexpected: true };
  const missingIssueField = syncIssue();
  delete missingIssueField.thread_id;
  const extraIssueField = { ...syncIssue(), unexpected: true };

  for (const payload of [
    { threads: [7], issues: [] },
    { threads: [missingTaskField], issues: [] },
    { threads: [extraTaskField], issues: [] },
    { threads: [syncThread({ state: 7 })], issues: [] },
    { threads: [syncThread({ memory_note: 7 })], issues: [] },
    { threads: [], issues: [7] },
    { threads: [], issues: [missingIssueField] },
    { threads: [], issues: [extraIssueField] },
    { threads: [], issues: [syncIssue({ message: null })] },
  ]) {
    assert.throws(
      () => parseSyncStatusSummary(JSON.stringify(payload)),
      /Invalid Codex sync status/,
    );
  }
});

test("parseSyncStatusSummary requires safe memory database row integers", () => {
  const valid = syncThread({ memory_database_rows: Number.MAX_SAFE_INTEGER });
  assert.equal(
    parseSyncStatusSummary(JSON.stringify({ threads: [valid], issues: [] })).memoryWarnings,
    1,
  );

  const unsafe = JSON.stringify({ threads: [syncThread()], issues: [] }).replace(
    '"memory_database_rows":0',
    '"memory_database_rows":9007199254740993',
  );
  assert.throws(
    () => parseSyncStatusSummary(unsafe),
    /threads\[0\]\.memory_database_rows/,
  );
});
