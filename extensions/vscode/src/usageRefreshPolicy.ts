import type { AgentStatus, RenderedReport } from "./types";

type UsageStatus = AgentStatus | RenderedReport["status"];

export function usageStatusFingerprint(status: UsageStatus): string {
  const { coverage } = status;
  const quota = status.plan_allowance;
  return JSON.stringify([
    status.ledger_revision,
    status.speed?.revision ?? null,
    status.speed?.metric_version ?? null,
    coverage.complete,
    coverage.fraction,
    coverage.stale_sources,
    coverage.pending_files,
    coverage.pending_bytes,
    quota?.probe_status ?? null,
    quota?.active_buckets.map(bucket => [bucket.limit_id, bucket.duration_minutes,
      bucket.resets_at !== null && bucket.resets_at <= Date.now() / 1000]) ?? null,
  ]);
}

export function usageReportNeedsRefresh(
  renderedFingerprint: string | undefined,
  status: UsageStatus,
): boolean {
  return renderedFingerprint !== undefined
    && renderedFingerprint !== usageStatusFingerprint(status);
}
