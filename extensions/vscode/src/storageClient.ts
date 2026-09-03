import * as vscode from "vscode";
import { AgentClient } from "./agentClient";
import type { AnalysisJob, StorageSnapshot, StorageTree } from "./types";

export class StorageClient {
  private inFlight = false;

  constructor(
    private readonly acquireClient: () => Promise<AgentClient | undefined>,
    private readonly output: vscode.OutputChannel,
    private readonly refreshDashboard: () => Promise<void>,
  ) {}

  async analyze(requestedTreeId?: unknown): Promise<void> {
    if (this.inFlight) {
      void vscode.window.showInformationMessage("A Task Storage analysis is already running.");
      return;
    }
    this.inFlight = true;
    try {
      const client = await this.acquireClient();
      if (!client) return;
      const snapshot = await client.get<StorageSnapshot>("/v1/storage/snapshot");
      const tree = await selectTree(snapshot.task_trees, requestedTreeId);
      if (!tree) return;
      const started = await client.post<AnalysisJob>("/v1/storage/jobs", { tree_id: tree.root_task_id });
      const result = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Analyzing task storage: ${tree.title || tree.root_task_id}`, cancellable: true },
        async (progress, cancellation) => monitorJob(client, started.operation_id, progress, cancellation),
      );
      if (result.state === "cancelled") {
        void vscode.window.showInformationMessage("Task Storage analysis cancelled; cached diagnostics were not replaced.");
      } else if (result.state === "failed") {
        throw new Error(result.error || "Task Storage analysis failed.");
      } else {
        this.output.appendLine(`[storage analysis] ${JSON.stringify(result.result)}`);
        await this.refreshDashboard();
        void vscode.window.showInformationMessage(`Task Storage analysis complete for ${tree.title || tree.root_task_id}.`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.output.appendLine(`[storage analysis error] ${message}`);
      void vscode.window.showErrorMessage(`Task Storage analysis failed: ${message}`);
    } finally {
      this.inFlight = false;
    }
  }
}

async function selectTree(trees: StorageTree[], requestedTreeId: unknown): Promise<StorageTree | undefined> {
  if (requestedTreeId !== undefined) {
    if (typeof requestedTreeId !== "string") throw new Error("Invalid Task Storage selection.");
    const selected = trees.find((tree) => tree.root_task_id === requestedTreeId);
    if (!selected) throw new Error("That task tree is no longer available. Refresh and try again.");
    return selected;
  }
  const picked = await vscode.window.showQuickPick(trees.map((tree) => ({
    label: tree.title || tree.root_task_id,
    description: `${formatBytes(tree.total_bytes)} · ${tree.project_label || "Unassigned"}`,
    detail: `${tree.descendant_count.toLocaleString()} descendants · ${tree.analysis_status === "complete" ? "Analyzed" : "Not analyzed"}`,
    tree,
  })), { title: "Analyze Task Storage", placeHolder: "Choose one task tree" });
  return picked?.tree;
}

async function monitorJob(
  client: AgentClient,
  operationId: string,
  progress: vscode.Progress<{ message?: string }>,
  cancellation: vscode.CancellationToken,
): Promise<AnalysisJob> {
  let cancellationSent = false;
  while (true) {
    if (cancellation.isCancellationRequested && !cancellationSent) {
      cancellationSent = true;
      await client.post(`/v1/jobs/${operationId}/cancel`);
      progress.report({ message: "Cancelling after the active worker batch" });
    }
    const status = await client.get<AnalysisJob>(`/v1/jobs/${operationId}`);
    const completed = numberField(status.progress, "completed_files");
    const total = numberField(status.progress, "total_files");
    if (total) progress.report({ message: `${completed}/${total} files` });
    if (["completed", "failed", "cancelled"].includes(status.state)) return status;
    await delay(cancellationSent ? 250 : 700);
  }
}

function numberField(value: Record<string, unknown>, key: string): number {
  return typeof value[key] === "number" ? value[key] : 0;
}

function formatBytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
