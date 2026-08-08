const assert = require("node:assert/strict");
const test = require("node:test");

const {
  backupFileName,
  buildStorageBackupArgs,
  buildStorageSnapshotArgs,
  parseBackupProgressLine,
  parseBackupResult,
  parseStorageSnapshot,
} = require("../out/storageBackupProtocol");

function snapshot() {
  return JSON.stringify({
    schema_version: 2,
    task_trees: [
      {
        root_task_id: "root-1234567890abcdef",
        title: "Review / main",
        project_key: "repo-a",
        project_label: "Repo A",
        total_bytes: 4096,
        root_bytes: 3072,
        descendant_bytes: 1024,
        descendant_count: 1,
        physical_file_count: 2,
        has_missing_root: false,
        has_relationship_cycle: false,
        duplicate_file_count: 0,
        recovery_ready: true,
        metadata_diagnostics: [],
      },
    ],
  });
}

test("storage snapshot groups task trees by project and backup args keep replace explicit", () => {
  const parsed = parseStorageSnapshot(snapshot());
  assert.equal(parsed.projects[0].projectLabel, "Repo A");
  assert.equal(parsed.projects[0].trees[0].rootTaskId, "root-1234567890abcdef");
  assert.deepEqual(buildStorageSnapshotArgs(), ["storage", "snapshot", "--json"]);
  assert.deepEqual(buildStorageBackupArgs({
    treeId: "root-1234567890abcdef",
    outputPath: "/tmp/backup.codex-task-backup",
    compression: "maximum",
    replace: true,
  }), [
    "storage", "backup", "--tree-id", "root-1234567890abcdef",
    "--output", "/tmp/backup.codex-task-backup", "--compression", "maximum",
    "--json", "--progress-json", "--replace",
  ]);
});

test("backup protocol validates progress, final result, and safe output names", () => {
  assert.deepEqual(parseBackupProgressLine('{"event":"progress","phase":"compressing","completed_bytes":4,"total_bytes":8,"file_index":1,"file_count":2}'), {
    event: "progress", phase: "compressing", completedBytes: 4, totalBytes: 8, fileIndex: 1, fileCount: 2,
  });
  assert.equal(parseBackupProgressLine('{"event":"progress","phase":"deleting"}'), undefined);
  assert.deepEqual(parseBackupResult(JSON.stringify({
    archive_path: "/tmp/task.codex-task-backup",
    source_bytes: 10,
    archive_bytes: 5,
    file_count: 2,
    recovery_ready: false,
    warnings: ["root missing"],
    archive_sha256: "abc",
    compression: "balanced",
  })).warnings, ["root missing"]);
  assert.equal(
    backupFileName("Review / main", "root-1234567890abcdef", new Date("2026-08-07T12:34:56.000Z")),
    "Review-main-root12345678-20260807T123456Z.codex-task-backup",
  );
});
