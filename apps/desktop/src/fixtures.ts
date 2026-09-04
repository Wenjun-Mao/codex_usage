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

const reportHtml = `<!doctype html><html lang="en" data-codex-theme="night"><head><meta charset="utf-8"><style>
:root{color-scheme:dark;--bg:#101316;--surface:#15191d;--soft:#1e242a;--text:#edf2f5;--muted:#9ba7b1;--line:#303840;--sol:#9bb8f2;--terra:#4f8ce8;--luna:#61c6ae}*{box-sizing:border-box}body{margin:0;padding:20px 24px 46px;background:var(--bg);color:var(--text);font:14px system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.4}.muted{color:var(--muted);font-size:12px}.metric-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:18px 0 24px;border-block:1px solid var(--line)}.metric-strip>div{min-width:0;padding:12px;border-right:1px solid var(--line)}.metric-strip>div:last-child{border-right:0}.metric-strip span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase}.metric-strip strong{display:block;margin-top:4px;font-size:20px;overflow-wrap:anywhere}.metric-strip small{display:block;margin-top:2px;color:var(--muted);font-size:10px}.section{border-top:1px solid var(--line);padding-top:18px;margin-top:22px}h2{font-size:17px;margin:0 0 4px}.help{margin:0 0 18px;color:var(--muted);font-size:12px}.project-scroll{overflow-x:auto}.project-grid{display:grid;grid-template-columns:145px minmax(210px,1fr) minmax(170px,.65fr) 185px;gap:8px 16px;align-items:center}.column{color:var(--muted);font-size:10px;font-weight:700;text-transform:uppercase}.project{text-align:right}.role-metric{font-size:11px;font-weight:650}.track{height:30px;background:var(--soft);display:flex;border-radius:4px;overflow:hidden}.sol{background:var(--sol)}.terra{background:var(--terra)}.luna{background:var(--luna)}.total{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}.legend{display:flex;gap:18px;margin:17px 0 0 161px;color:var(--muted);font-size:11px}.swatch{display:inline-block;width:10px;height:10px;margin-right:6px;border:1px solid var(--line);border-radius:2px;vertical-align:-1px}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:9px;border-bottom:1px solid var(--line)}th{background:var(--soft);color:var(--muted);font-size:11px}th:first-child,td:first-child{text-align:left}@media(max-width:720px){body{padding:16px}.metric-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.metric-strip>div{border-bottom:1px solid var(--line)}.metric-strip>div:nth-child(2n){border-right:0}.metric-strip>div:last-child{grid-column:1/-1;border-bottom:0}.project-grid{min-width:628px;grid-template-columns:90px minmax(190px,1fr) minmax(150px,.65fr) 150px}.legend{margin-left:106px}}
</style></head><body><div class="muted">Usage range: 7 days · Pricing table as of 2026-09-02</div><div class="muted">Pricing uses rates effective at each usage event.</div><section class="metric-strip" aria-label="Usage summary"><div><span>Total tokens</span><strong>903.9M</strong><small>6,418 usage events</small></div><div><span>API-equivalent cost</span><strong>$437.45</strong><small>100% priced</small></div><div><span>Codex credits</span><strong>13,837</strong><small>100% credit-priced</small></div><div><span>Cache hit share</span><strong>97.8%</strong><small>881.7M cached input</small></div><div><span>API-excluded tokens</span><strong>0</strong><small>All models have rates</small></div></section><section class="section"><h2>Project Breakdown</h2><p class="help">Root task token usage includes side chats stored in the parent task.</p><div class="project-scroll"><div class="project-grid"><span class="column project">Project</span><span class="column">Root tasks</span><span class="column">Subagents</span><span class="column">Total</span><strong class="project">uk_dev</strong><div><div class="role-metric">371.3M · 70.0%</div><div class="track"><span class="sol" style="width:76%"></span><span class="terra" style="width:24%"></span></div></div><div><div class="role-metric">159.1M · 30.0%</div><div class="track"><span class="terra" style="width:82%"></span><span class="luna" style="width:18%"></span></div></div><span class="total">530.4M · $258.29 · 8,181 cr</span><strong class="project">codex_usage</strong><div><div class="role-metric">164.2M · 81.4%</div><div class="track"><span class="sol" style="width:62%"></span><span class="terra" style="width:38%"></span></div></div><div><div class="role-metric">37.4M · 18.6%</div><div class="track"><span class="terra" style="width:100%"></span></div></div><span class="total">201.6M · $97.12 · 3,044 cr</span><strong class="project">persona_generators</strong><div><div class="role-metric">107.5M · 62.5%</div><div class="track"><span class="sol" style="width:100%"></span></div></div><div><div class="role-metric">64.4M · 37.5%</div><div class="track"><span class="luna" style="width:100%"></span></div></div><span class="total">171.9M · $82.04 · 2,611 cr</span></div></div><div class="legend"><span><i class="swatch sol"></i>gpt-5.6-sol</span><span><i class="swatch terra"></i>gpt-5.6-terra</span><span><i class="swatch luna"></i>gpt-5.6-luna</span></div></section><section class="section"><h2>Model Mix</h2><table><thead><tr><th>Model</th><th>Total</th><th>Input</th><th>Output</th><th>Credits</th></tr></thead><tbody><tr><td>gpt-5.6-sol</td><td>608.2M</td><td>605.8M</td><td>2.4M</td><td>9,654</td></tr><tr><td>gpt-5.6-terra</td><td>231.3M</td><td>230.5M</td><td>0.8M</td><td>3,507</td></tr><tr><td>gpt-5.6-luna</td><td>64.4M</td><td>64.2M</td><td>0.2M</td><td>676</td></tr></tbody></table></section></body></html>`;

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
