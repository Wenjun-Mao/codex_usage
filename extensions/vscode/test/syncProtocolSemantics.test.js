const assert = require("node:assert/strict");
const test = require("node:test");

const {
  parseSyncRunResult,
  parseSyncStatusSummary,
} = require("../out/syncProtocol");

function taskRow(overrides = {}) {
  return {
    thread_id: "task-1",
    state: "local_ahead",
    action: "push",
    reason: "local task changed",
    local_path: "/codex/task-1.jsonl",
    remote_path: "/transfer/tasks/task-1.jsonl",
    local_sha256: "local-hash",
    remote_sha256: "remote-hash",
    base_sha256: "base-hash",
    updated_at: "2026-07-16T12:00:00Z",
    source_relative_path: "2026/07/16/task-1.jsonl",
    project_key: "repo",
    project_label: "Repo",
    memory_database_rows: 0,
    ...overrides,
  };
}

function runResult(threads) {
  return {
    outcome: "completed",
    counts: {
      discovered: threads.length,
      selected: threads.length,
      remote: 0,
      pulled: 0,
      pushed: 0,
      unchanged: 0,
      conflicts: 0,
      issues: 0,
    },
    timings_ms: { discovery: 0, planning: 0, pull: 0, push: 0, index: 0, total: 0 },
    threads,
    pulled: [],
    pushed: [],
    issues: [],
  };
}

const INVALID_ROWS = [
  taskRow({ thread_id: "" }),
  taskRow({ thread_id: " task-1 " }),
  taskRow({ state: "unknown_state" }),
  taskRow({ action: "unknown_action" }),
  taskRow({ state: "synced", action: "pull" }),
];

test("result parser rejects noncanonical duplicate and semantically invalid task rows", () => {
  for (const row of INVALID_ROWS) {
    assert.throws(
      () => parseSyncRunResult(JSON.stringify(runResult([row]))),
      /Invalid Codex sync result/,
    );
  }
  assert.throws(
    () => parseSyncRunResult(JSON.stringify(runResult([taskRow(), taskRow()]))),
    /Invalid Codex sync result/,
  );
});

test("status parser rejects noncanonical duplicate and semantically invalid task rows", () => {
  for (const row of INVALID_ROWS) {
    assert.throws(
      () => parseSyncStatusSummary(JSON.stringify({ threads: [row], issues: [] })),
      /Invalid Codex sync status/,
    );
  }
  assert.throws(
    () => parseSyncStatusSummary(JSON.stringify({
      threads: [taskRow(), taskRow()],
      issues: [],
    })),
    /Invalid Codex sync status/,
  );
});

test("status and result parsers accept every exact planner state and action pair", () => {
  const pairs = [
    ["synced", "none"],
    ["local_only", "push"],
    ["remote_only", "pull"],
    ["missing", "skip"],
    ["local_ahead", "push"],
    ["remote_ahead", "pull"],
    ["fast_forward_push", "push"],
    ["fast_forward_pull", "pull"],
    ["conflict", "conflict"],
    ["issue", "issue"],
    ["project_rebind", "pull"],
  ];
  const rows = pairs.map(([state, action], index) => taskRow({
    thread_id: `task-${index + 1}`,
    state,
    action,
  }));

  assert.equal(
    parseSyncStatusSummary(JSON.stringify({ threads: rows, issues: [] })).total,
    pairs.length,
  );
  assert.equal(
    parseSyncRunResult(JSON.stringify(runResult(rows))).threads.length,
    pairs.length,
  );
});
