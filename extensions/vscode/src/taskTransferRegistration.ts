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

export function formatTaskRegistrationFailureLog(threadId: string): string {
  return (
    `[task registration] ${threadId}: ` +
    "Codex registration could not be completed"
  );
}

function uniqueThreadIds(threadIds: readonly string[]): string[] {
  return [...new Set(threadIds)];
}
