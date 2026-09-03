export type ReportRange = "today" | "yesterday" | "7d" | "30d" | "month" | "all";
export type ReportTheme = "auto" | "day" | "night";
export type ReportView = "usage" | "storage";

export interface AgentStatus {
  capture_running: boolean;
  next_capture_seconds: number | null;
  dirty_paths: number;
  ledger_revision: number;
  last_capture_at: string;
  last_capture_outcome: string;
  last_capture_error: string;
  coverage: {
    complete: boolean;
    fraction: number;
    stale_sources: number;
    pending_files: number;
    pending_bytes: number;
  };
}

export interface AgentSettings {
  codex_home: string;
  capture_interval_minutes: number | null;
  background_capture: boolean;
  daily_update_checks: boolean;
  theme: ReportTheme;
  transfer_folder: string;
}

export interface ProjectSummary {
  project_key: string;
  project_label: string;
  task_count: number;
}

export interface RenderedReport {
  html: string;
  ledger_revision: number;
  cache_hit: boolean;
  elapsed_seconds: number;
  status: Pick<AgentStatus, "ledger_revision" | "last_capture_at" | "last_capture_outcome" | "last_capture_error" | "coverage">;
}

export interface StorageTree {
  root_task_id: string;
  title: string;
  project_label: string;
  total_bytes: number;
  root_bytes: number;
  descendant_bytes: number;
  descendant_count: number;
  analysis_status: string;
  has_history_amplification: boolean;
  has_media_amplification: boolean;
  has_active_root_history_risk: boolean;
  has_missing_root: boolean;
}

export interface StorageSnapshot {
  totals: {
    total_bytes: number;
    root_bytes: number;
    descendant_bytes: number;
    task_tree_count: number;
    physical_file_count: number;
  };
  task_trees: StorageTree[];
  diagnostics: string[];
}

export interface AnalysisJob {
  operation_id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
}

export interface TransferTask {
  thread_id: string;
  title: string;
  updated_at: string;
  estimated_sync_bytes: number;
  availability: "local" | "remote" | "both";
}

export interface TransferProject {
  project_key: string;
  project_label: string;
  identity_kind: "git" | "path";
  candidate_roots: string[];
  tasks: TransferTask[];
}

export interface TransferInventory {
  projects: TransferProject[];
  issues: Array<{ code: string; message: string; thread_id: string }>;
}
