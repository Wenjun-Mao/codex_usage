import type { AgentRequest } from "./host";
import type {
  AgentSettings,
  AgentStatus,
  MigrationPlan,
  ProjectSummary,
  RenderedReport,
  ServiceStatus,
  StorageSnapshot,
  TransferInventory,
} from "./types";
import { usageReportHtml } from "./usageFixtureReport";

const FIXTURE_NOW = new Date("2026-09-02T16:00:00.000Z").getTime();

const status: AgentStatus = {
  agent_pid: 58241,
  api_version: 1,
  codex_home: "/Users/demo/.codex",
  capture_running: false,
  next_capture_seconds: 684,
  dirty_paths: 3,
  ledger_revision: 82,
  last_capture_at: new Date(FIXTURE_NOW - 216_000).toISOString(),
  last_capture_outcome: "success",
  last_capture_error: "",
  coverage: {
    complete: true,
    fraction: 1,
    total_sources: 428,
    captured_sources: 428,
    stale_sources: 0,
    pending_files: 0,
    pending_bytes: 0,
    total_bytes: 214_832_198_114,
    captured_bytes: 214_832_198_114,
  },
};

const settings: AgentSettings = {
  schema_version: 1,
  codex_home: status.codex_home,
  capture_interval_minutes: 15,
  background_capture: true,
  daily_update_checks: false,
  onboarding_complete: true,
  native_onboarding_complete: true,
  timezone: null,
  theme: "night",
  auto_project_transitions: true,
  transfer_folder: "/Users/demo/Library/CloudStorage/OneDrive/Codex",
};

const projects: ProjectSummary[] = [
  { project_key: "codex_usage", project_label: "codex_usage", project_aliases: [], task_count: 5 },
  { project_key: "uk_dev", project_label: "uk_dev", project_aliases: [], task_count: 12 },
  { project_key: "persona_generators", project_label: "persona_generators", project_aliases: [], task_count: 2 },
];

const reportHtml = usageReportHtml;

const storage: StorageSnapshot = {
  schema_version: 4,
  totals: {
    total_bytes: 214_832_198_114,
    root_bytes: 11_240_168_201,
    descendant_bytes: 203_592_029_913,
    active_bytes: 184_663_106_113,
    archived_bytes: 30_169_092_001,
    physical_file_count: 2525,
    task_tree_count: 91,
  },
  diagnostics: [],
  task_trees: [
    { root_task_id: "019f-root-a", title: "Ship native persistent collector", project_key: "codex_usage", project_label: "codex_usage", root_bytes: 1_104_824_320, descendant_bytes: 63_992_310_784, descendant_count: 286, total_bytes: 65_097_135_104, share: .303, active_file_count: 287, archived_file_count: 0, analysis_status: "complete", analysis_coverage: 1, compacted_share: .84, large_descendant_share: .91, has_history_amplification: true, has_media_amplification: false, has_active_root_history_risk: true, has_missing_root: false, metadata_diagnostics: [] },
    { root_task_id: "019f-root-b", title: "Migrate TikTok mini games", project_key: "uk_dev", project_label: "uk_dev", root_bytes: 8_984_932_352, descendant_bytes: 42_037_264_384, descendant_count: 163, total_bytes: 51_022_196_736, share: .237, active_file_count: 160, archived_file_count: 4, analysis_status: "not_analyzed", analysis_coverage: 0, compacted_share: 0, large_descendant_share: 0, has_history_amplification: false, has_media_amplification: false, has_active_root_history_risk: false, has_missing_root: false, metadata_diagnostics: [] },
    { root_task_id: "019f-root-c", title: "Plan persona generation workflow", project_key: "persona_generators", project_label: "persona_generators", root_bytes: 721_420_288, descendant_bytes: 11_882_577_920, descendant_count: 44, total_bytes: 12_603_998_208, share: .059, active_file_count: 45, archived_file_count: 0, analysis_status: "complete", analysis_coverage: 1, compacted_share: .22, large_descendant_share: .41, has_history_amplification: false, has_media_amplification: true, has_active_root_history_risk: false, has_missing_root: false, metadata_diagnostics: [] },
  ],
};

const transfer: TransferInventory = {
  inventory_version: 3,
  issues: [],
  projects: projects.map((project, index) => ({
    project_key: project.project_key,
    project_label: project.project_label,
    identity_kind: "path",
    candidate_roots: [`/Users/demo/projects/${project.project_label}`],
    tasks: Array.from({ length: index + 2 }, (_, taskIndex) => ({
      thread_id: `019f-${index}-${taskIndex}`,
      title: ["Native app architecture", "Review ledger integrity", "Task Transfer verification", "Polish dashboard"][(index + taskIndex) % 4] ?? "Codex task",
      updated_at: new Date(FIXTURE_NOW - taskIndex * 86_400_000).toISOString(),
      estimated_sync_bytes: (taskIndex + 1) * 1_720_320,
      availability: taskIndex % 2 ? "both" : "local",
    })),
  })),
};

const migration: MigrationPlan = {
  candidates: [],
  conflicts: [],
  importable_generations: 0,
  identical_generations: 0,
  superseding_generations: 0,
  requires_precedence: false,
};

const service: ServiceStatus = { supported: true, installed: true, detail: "User background agent" };

export async function fixtureRequest<T>(request: AgentRequest): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, request.path.includes("capture") ? 480 : 80));
  if (request.path === "/v1/health") return { ok: true, api_version: 1, status } as T;
  if (request.path === "/v1/status") return status as T;
  if (request.path === "/v1/settings") {
    if (request.method === "POST") Object.assign(settings, request.body);
    return settings as T;
  }
  if (request.path === "/v1/projects") return { projects } as T;
  if (request.path.startsWith("/v1/report")) {
    return { html: reportHtml, ledger_revision: 82, cache_hit: true, elapsed_seconds: .038, status } as RenderedReport as T;
  }
  if (request.path.startsWith("/v1/storage/snapshot")) return storage as T;
  if (request.path === "/v1/storage/jobs") return { operation_id: "fixture-analysis", kind: "storage-analysis", state: "queued", progress: {}, result: {}, error: "" } as T;
  if (request.path === "/v1/jobs/fixture-analysis") return { operation_id: "fixture-analysis", kind: "storage-analysis", state: "completed", progress: { completed_files: 8, total_files: 8 }, result: { tree_id: "fixture", files_total: 8, files_analyzed: 8 }, error: "" } as T;
  if (request.path === "/v1/jobs/fixture-analysis/cancel") return { operation_id: "fixture-analysis", state: "cancelled" } as T;
  if (request.path === "/v1/transfer/inventory") return transfer as T;
  if (request.path === "/v1/transfer/execute") return { operation: request.body?.operation, result: { outcome: "completed", counts: { pushed: 1, pulled: 0 } }, integration: {} } as T;
  if (request.path === "/v1/migration/plan") return migration as T;
  if (request.path === "/v1/migration/run") return { imported_caches: 0, skipped_caches: 0 } as T;
  if (request.path === "/v1/service") return service as T;
  if (request.path === "/v1/capture") return { outcome: "success", elapsed_seconds: 0.48, status } as T;
  throw new Error(`No development fixture for ${request.method} ${request.path}`);
}
