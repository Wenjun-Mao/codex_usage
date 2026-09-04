import type { AgentStatus, RenderedReport } from "./types";

type UsageStatus = AgentStatus | RenderedReport["status"];

export function usageStatusFingerprint(status: UsageStatus): string {
  const { coverage } = status;
  return JSON.stringify([
    status.ledger_revision,
    coverage.complete,
    coverage.fraction,
    coverage.stale_sources,
    coverage.pending_files,
    coverage.pending_bytes,
  ]);
}

export function usageReportNeedsRefresh(
  renderedFingerprint: string | undefined,
  status: UsageStatus,
): boolean {
  return renderedFingerprint !== undefined
    && renderedFingerprint !== usageStatusFingerprint(status);
}
