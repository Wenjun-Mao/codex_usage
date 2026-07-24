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
  if (result.outcome !== "completed" && result.outcome !== "issue") {
    return [];
  }
  const selected = uniqueThreadIds(selectedThreadIds);
  const selectedSet = new Set(selected);
  if (
    result.counts.pulled !== result.pulled.length ||
    result.pulled.some((threadId) => !isCanonicalThreadId(threadId)) ||
    new Set(result.pulled).size !== result.pulled.length ||
    result.pulled.some((threadId) => !selectedSet.has(threadId))
  ) {
    return [];
  }
  return result.outcome === "completed" ? selected : [...result.pulled];
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

function isCanonicalThreadId(threadId: string): boolean {
  return threadId.length > 0 && threadId === threadId.trim();
}
