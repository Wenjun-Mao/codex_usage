import type { SyncRunResult } from "./syncProtocol";

export type TaskRegistrationSummary = {
  attempted: number;
  registered: number;
  failed: number;
};

export function certifiedImportThreadIds(
  result: SyncRunResult,
  selectedThreadIds: readonly string[],
): string[] {
  if (result.outcome === "completed") {
    return uniqueThreadIds(selectedThreadIds);
  }
  if (result.pulled.length > 0) {
    return uniqueThreadIds(result.pulled);
  }
  return [];
}

function uniqueThreadIds(threadIds: readonly string[]): string[] {
  return [...new Set(threadIds)];
}
