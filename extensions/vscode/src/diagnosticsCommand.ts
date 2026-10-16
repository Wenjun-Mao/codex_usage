import type * as vscode from "vscode";
import { AgentClient, AgentRequestError } from "./agentClient";

interface DiagnosticsClient {
  get<T>(requestPath: string): Promise<T>;
}

export function registerDiagnosticsCommand(
  context: vscode.ExtensionContext,
  ui: typeof vscode,
  discover: () => Promise<DiagnosticsClient> = () => AgentClient.discover(),
): void {
  context.subscriptions.push(ui.commands.registerCommand("codexUsage.copyDiagnostics", async () => {
    try {
      // Discover only: copying support evidence must never launch a collector.
      const client = await discover();
      const payload = await client.get<unknown>("/v1/allowance/diagnostics");
      if (typeof payload !== "object" || payload === null
        || !("schema_version" in payload) || payload.schema_version !== 1
        || !("text" in payload) || typeof payload.text !== "string"
        || !payload.text.trim() || Buffer.byteLength(payload.text, "utf8") > 48 * 1024) {
        throw new Error("The collector returned unsupported diagnostics.");
      }
      await ui.env.clipboard.writeText(payload.text);
      void ui.window.showInformationMessage("Allowance diagnostics copied. Review before sharing.");
    } catch (error) {
      const detail = error instanceof AgentRequestError && error.status === 404
        ? "Update the collector to use Copy Diagnostics."
        : error instanceof Error ? error.message : String(error);
      void ui.window.showErrorMessage(`Could not copy diagnostics: ${detail}`);
    }
  }));
}
