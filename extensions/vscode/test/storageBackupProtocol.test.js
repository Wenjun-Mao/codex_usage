const assert = require("node:assert/strict");
const test = require("node:test");

const {
  backupFileName,
  buildStorageAnalyzeArgs,
  buildStorageBackupArgs,
  buildStorageRolloverArgs,
  buildStorageSnapshotArgs,
  parseAnalysisProgressLine,
  parseAnalysisResult,
  parseBackupProgressLine,
  parseBackupResult,
  parseRolloverResult,
  parseStorageSnapshot,
} = require("../out/storageBackupProtocol");

function snapshot() {
  return JSON.stringify({
    schema_version: 3,
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
        analysis_status: "complete",
        analysis_complete: true,
        analyzed_bytes: 4096,
        analysis_coverage: 1,
        compacted_record_count: 2,
        compacted_bytes: 2048,
        compacted_share: 0.5,
        largest_compacted_record_bytes: 1536,
        media_compacted_record_count: 1,
        embedded_media_occurrence_count: 2,
        large_descendant_file_count: 0,
        large_descendant_bytes: 0,
        large_descendant_share: 0,
        active_root_compacted_bytes: 2048,
        has_history_amplification: false,
        has_media_amplification: false,
        has_active_root_history_risk: false,
        can_prepare_rollover: true,
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
  assert.deepEqual(buildStorageAnalyzeArgs("root-1234567890abcdef"), [
    "storage", "analyze", "--tree-id", "root-1234567890abcdef", "--json", "--progress-json",
  ]);
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
  assert.deepEqual(buildStorageRolloverArgs({
    treeId: "root-1234567890abcdef",
    outputPath: "/tmp/rollover.codex-task-backup",
    compression: "balanced",
  }), [
    "storage", "rollover", "--tree-id", "root-1234567890abcdef",
    "--output", "/tmp/rollover.codex-task-backup", "--compression", "balanced",
    "--json", "--progress-json",
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

test("analysis and rollover protocols reject malformed state and preserve results", () => {
  assert.deepEqual(parseAnalysisProgressLine(JSON.stringify({
    phase: "analyzing", completed_files: 1, total_files: 2,
    completed_bytes: 10, total_bytes: 20, path: "/tmp/task.jsonl",
  })), {
    phase: "analyzing", completedFiles: 1, totalFiles: 2,
    completedBytes: 10, totalBytes: 20, path: "/tmp/task.jsonl",
  });
  assert.equal(parseAnalysisProgressLine('{"phase":"deleting"}'), undefined);
  assert.equal(parseAnalysisResult(JSON.stringify({
    schema_version: 1,
    analysis: {
      tree_id: "root", files_total: 2, files_analyzed: 1, files_unchanged: 1,
      files_appended: 1, full_scans: 0, append_fallbacks: 0,
      source_bytes_read: 100, worker_count: 2,
    },
  })).sourceBytesRead, 100);
  const rollover = parseRolloverResult(JSON.stringify({
    schema_version: 1,
    backup: {
      archive_path: "/tmp/task.codex-task-backup", source_bytes: 10,
      archive_bytes: 5, file_count: 1, recovery_ready: true, warnings: [],
      archive_sha256: "abc", compression: "maximum",
    },
    task_title: "Task", project_label: "Project", starter_prompt: "Continue",
    checklist: ["Create a fresh task"],
  }));
  assert.equal(rollover.starterPrompt, "Continue");
  assert.deepEqual(rollover.checklist, ["Create a fresh task"]);
});
