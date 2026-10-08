import * as vscode from "vscode";
import type { AgentClient } from "./agentClient";

export async function migrateLegacyUsage(client: AgentClient): Promise<boolean> {
  const plan = await client.get<LegacyMigrationPlan>("/v1/migration/plan");
  if (!plan.candidates.length) {
    void vscode.window.showInformationMessage("No compatible legacy Codex Usage caches were found for this CODEX_HOME.");
    return false;
  }
  const precedence: Record<string, string> = {};
  for (const conflict of plan.conflicts) {
    const selected = await vscode.window.showQuickPick(
      conflict.sources.map((source) => ({ label: source, source })),
      {
        title: "Choose a migration source",
        placeHolder: `Histories disagree for ${conflict.file_key}. Choose the source to retain.`,
      },
    );
    if (!selected) return false;
    precedence[conflict.file_key] = selected.source;
  }
  const result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Migrating ${plan.candidates.length} legacy ${plan.candidates.length === 1 ? "cache" : "caches"}`,
    },
    () => client.post<LegacyMigrationResult>("/v1/migration/run", { precedence }),
  );
  void vscode.window.showInformationMessage(
    `Migration complete: ${result.imported_caches} imported, ${result.skipped_caches} already present.`,
  );
  return true;
}

interface LegacyMigrationPlan {
  candidates: Array<{ path: string; digest: string; source_kind: string }>;
  conflicts: Array<{ file_key: string; sources: string[]; reason: string }>;
  importable_generations: number;
  identical_generations: number;
  superseding_generations: number;
  requires_precedence: boolean;
}

interface LegacyMigrationResult {
  imported_caches: number;
  skipped_caches: number;
  ledger_revision: number;
  ledger_changed: boolean;
  plan: LegacyMigrationPlan;
}
