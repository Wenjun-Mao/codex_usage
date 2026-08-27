const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildStorageAnalyzeArgs,
  buildStorageSnapshotArgs,
  parseAnalysisProgressLine,
  parseAnalysisResult,
  parseStorageSnapshot,
} = require("../out/storageProtocol");

function snapshot(schemaVersion = 4) {
  return JSON.stringify({
    schema_version: schemaVersion,
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
        analysis_status: "complete",
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
        metadata_diagnostics: [],
      },
    ],
  });
}

test("storage snapshot schema four groups task trees and builds read-only args", () => {
  const parsed = parseStorageSnapshot(snapshot());
  assert.equal(parsed.projects[0].projectLabel, "Repo A");
  assert.equal(parsed.projects[0].trees[0].rootTaskId, "root-1234567890abcdef");
  assert.deepEqual(buildStorageSnapshotArgs(), ["storage", "snapshot", "--json"]);
  assert.deepEqual(buildStorageAnalyzeArgs("root-1234567890abcdef"), [
    "storage", "analyze", "--tree-id", "root-1234567890abcdef", "--json", "--progress-json",
  ]);
  assert.throws(() => parseStorageSnapshot(snapshot(3)), /schema_version must be 4/);
});

test("analysis protocol validates progress and preserves final diagnostics", () => {
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
});
