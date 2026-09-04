export type Theme = "auto" | "day" | "night";
export type ViewName = "usage" | "storage" | "transfer" | "settings";
export type CaptureInterval = number | null;

export interface AgentSettings {
  schema_version: number;
  codex_home: string;
  capture_interval_minutes: CaptureInterval;
  background_capture: boolean;
  daily_update_checks: boolean;
  onboarding_complete: boolean;
  native_onboarding_complete: boolean;
  timezone: string | null;
  theme: Theme;
  auto_project_transitions: boolean;
  transfer_folder: string;
}

export interface Coverage {
  complete: boolean;
  fraction: number;
  total_sources: number;
  captured_sources: number;
  stale_sources: number;
  pending_files: number;
  pending_bytes: number;
  total_bytes: number;
  captured_bytes: number;
}

export interface AgentStatus {
  agent_pid: number;
  api_version: number;
  codex_home: string;
  capture_running: boolean;
  next_capture_seconds: number | null;
  dirty_paths: number;
  ledger_revision: number;
  last_capture_at: string;
  last_capture_outcome: string;
  last_capture_error: string;
  coverage: Coverage;
}

export interface AgentHealth {
  ok: boolean;
  api_version: number;
  status: AgentStatus;
}

export interface ProjectSummary {
  project_key: string;
  project_label: string;
  project_aliases: string[];
  task_count: number;
}

export interface RenderedReport {
  html: string;
  ledger_revision: number;
  cache_hit: boolean;
  elapsed_seconds: number;
  status: Omit<AgentStatus, "agent_pid" | "api_version" | "codex_home" | "capture_running" | "next_capture_seconds" | "dirty_paths">;
}

export interface StorageTotals {
  total_bytes: number;
  root_bytes: number;
  descendant_bytes: number;
  active_bytes: number;
  archived_bytes: number;
  physical_file_count: number;
  task_tree_count: number;
}

export interface StorageTree {
  root_task_id: string;
  title: string;
  project_key: string;
  project_label: string;
  root_bytes: number;
  descendant_bytes: number;
  descendant_count: number;
  total_bytes: number;
  share: number;
  active_file_count: number;
  archived_file_count: number;
  analysis_status: string;
  analysis_coverage: number;
  compacted_share: number;
  large_descendant_share: number;
  has_history_amplification: boolean;
  has_media_amplification: boolean;
  has_active_root_history_risk: boolean;
  has_missing_root: boolean;
  metadata_diagnostics: string[];
}

export interface StorageSnapshot {
  schema_version: number;
  totals: StorageTotals;
  task_trees: StorageTree[];
  diagnostics: string[];
}

export type TaskAvailability = "local" | "remote" | "both";

export interface TransferTask {
  thread_id: string;
  title: string;
  updated_at: string;
  estimated_sync_bytes: number;
  availability: TaskAvailability;
}

export interface TransferProject {
  project_key: string;
  project_label: string;
  identity_kind: "git" | "path";
  candidate_roots: string[];
  tasks: TransferTask[];
}

export interface TransferInventory {
  inventory_version: number;
  projects: TransferProject[];
  issues: Array<{ code: string; message: string; thread_id: string }>;
}

export interface MigrationConflict {
  file_key: string;
  sources: string[];
  reason: string;
}

export interface MigrationPlan {
  candidates: Array<{ path: string; digest: string; source_kind: string }>;
  conflicts: MigrationConflict[];
  importable_generations: number;
  identical_generations: number;
  superseding_generations: number;
  requires_precedence: boolean;
}

export interface ServiceStatus {
  supported: boolean;
  installed: boolean;
  detail: string;
}

export interface UpdateInfo {
  available: boolean;
  current_version: string;
  version: string;
  date: string | null;
  body: string | null;
}
