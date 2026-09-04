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

const reportHtml = `<!doctype html><html><head><meta charset="utf-8"><style>
:root{color-scheme:dark;--bg:#101214;--text:#edf0f3;--muted:#a7afb9;--line:#343a42;--track:#232932;--root:#8faef3;--sub:#e1a72c}*{box-sizing:border-box}body{margin:0;padding:22px 26px 48px;background:var(--bg);color:var(--text);font:14px system-ui,-apple-system,Segoe UI,sans-serif}h1{font-size:25px;margin:0 0 6px}p{color:var(--muted);margin:0 0 28px}.section{border-top:1px solid var(--line);padding-top:24px;margin-top:24px}h2{font-size:18px;margin:0 0 16px}.row{display:grid;grid-template-columns:170px minmax(280px,1fr) 210px;gap:16px;align-items:center;margin:13px 0}.label{text-align:right}.bar{height:34px;background:var(--track);display:flex;border-radius:5px;overflow:hidden}.root{background:var(--root)}.sub{background:var(--sub)}.metric{color:var(--muted)}.legend{display:flex;gap:18px;margin:18px 0 0 186px;color:var(--muted)}.swatch{display:inline-block;width:11px;height:11px;margin-right:6px;border-radius:2px}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:10px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}@media(max-width:760px){.row{grid-template-columns:110px 1fr}.metric{grid-column:2}.legend{margin-left:126px}}
</style></head><body><h1>Usage Summary</h1><p>Sep 1, 2026 through Sep 2, 2026 · Local ledger revision 82</p><div class="section"><h2>Project Breakdown</h2><div class="row"><div class="label">uk_dev</div><div class="bar"><span class="root" style="width:70%"></span><span class="sub" style="width:30%"></span></div><div class="metric">530.4M · $258.29 · 8,181 cr</div></div><div class="row"><div class="label">codex_usage</div><div class="bar"><span class="root" style="width:31%"></span><span class="sub" style="width:7%"></span></div><div class="metric">201.6M · $97.12 · 3,044 cr</div></div><div class="row"><div class="label">persona_generators</div><div class="bar"><span class="root" style="width:20%"></span><span class="sub" style="width:12%"></span></div><div class="metric">171.9M · $82.04 · 2,611 cr</div></div><div class="legend"><span><i class="swatch root"></i>Root tasks</span><span><i class="swatch sub"></i>Subagents</span></div></div><div class="section"><h2>Model Mix</h2><table><thead><tr><th>Model</th><th>Total</th><th>Input</th><th>Output</th><th>Credits</th></tr></thead><tbody><tr><td>gpt-5.6-sol</td><td>608.2M</td><td>605.8M</td><td>2.4M</td><td>9,654</td></tr><tr><td>gpt-5.6-terra</td><td>295.7M</td><td>294.8M</td><td>0.9M</td><td>4,182</td></tr></tbody></table></div></body></html>`;

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
