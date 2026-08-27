import * as vscode from "vscode";

import {
  StorageOperationCancelledError,
  runStorageOperation,
} from "./storageOperationProcess";
import {
  buildStorageAnalyzeArgs,
  buildStorageSnapshotArgs,
  formatStorageBytes,
  parseAnalysisProgressLine,
  parseAnalysisResult,
  parseStorageSnapshot,
  type StorageTree,
} from "./storageProtocol";
import { chooseStorageTree } from "./storageTreePicker";

type CommandResult = { stdout: string; stderr: string };

export type StorageDiagnosticsDependencies = {
  output: vscode.OutputChannel;
  resolveExecutable(): Promise<string>;
  processEnv(): NodeJS.ProcessEnv;
  runCommand(args: string[]): Promise<CommandResult>;
  refreshUi(): Promise<void>;
};

export class StorageDiagnosticsController {
  private inFlight = false;

  constructor(private readonly dependencies: StorageDiagnosticsDependencies) {}

  async analyze(requestedTreeId?: unknown): Promise<void> {
    await this.runExclusive("analysis", async () => {
      const tree = await this.resolveTree(requestedTreeId, {
        actionTitle: "Analyze Task Storage",
        actionVerb: "analyze",
      });
      if (!tree) {
        return;
      }
      const executablePath = await this.dependencies.resolveExecutable();
      const args = buildStorageAnalyzeArgs(tree.rootTaskId);
      this.dependencies.output.appendLine(`> ${executablePath} ${args.join(" ")}`);
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `Analyzing task storage: ${tree.title || tree.rootTaskId}`,
          cancellable: true,
        },
        async (progress, cancellationToken) => runStorageOperation({
          executablePath,
          args,
          env: this.dependencies.processEnv(),
          cancellationToken,
          parseProgressLine: parseAnalysisProgressLine,
          parseResult: parseAnalysisResult,
          onProgress: (event) => progress.report({
            message: `${event.completedFiles}/${event.totalFiles} files | ${formatStorageBytes(event.completedBytes)} read`,
          }),
          onOutput: (text) => this.dependencies.output.append(text),
        }),
      );
      this.dependencies.output.appendLine(
        `[storage analysis] tree=${result.treeId} files=${result.filesTotal} ` +
        `read=${result.sourceBytesRead} workers=${result.workerCount}`,
      );
      await this.dependencies.refreshUi();
      void vscode.window.showInformationMessage(
        `Task storage analysis complete for ${tree.title || tree.rootTaskId}.`,
      );
    });
  }

  private async resolveTree(
    requestedTreeId: unknown,
    pickerCopy: { actionTitle: string; actionVerb: string },
  ): Promise<StorageTree | undefined> {
    const snapshotResult = await this.dependencies.runCommand(buildStorageSnapshotArgs());
    const snapshot = parseStorageSnapshot(snapshotResult.stdout);
    if (requestedTreeId !== undefined) {
      if (typeof requestedTreeId !== "string" || !requestedTreeId.trim()) {
        throw new Error("Invalid Task Storage action. Refresh the dashboard and try again.");
      }
      const tree = snapshot.trees.find((candidate) => candidate.rootTaskId === requestedTreeId);
      if (!tree) {
        throw new Error("This Task Storage row is no longer available. Refresh the dashboard and try again.");
      }
      return tree;
    }
    return chooseStorageTree(snapshot.projects, pickerCopy);
  }

  private async runExclusive(label: string, action: () => Promise<void>): Promise<void> {
    if (this.inFlight) {
      void vscode.window.showInformationMessage("A Task Storage operation is already running.");
      return;
    }
    this.inFlight = true;
    try {
      await action();
    } catch (error) {
      if (error instanceof StorageOperationCancelledError) {
        this.dependencies.output.appendLine(`[${label}] cancelled; cached state was not replaced.`);
        void vscode.window.showInformationMessage(`Task Storage ${label} cancelled.`);
      } else {
        const message = error instanceof Error ? error.message : String(error);
        this.dependencies.output.appendLine(`[${label} error] ${message}`);
        void vscode.window.showErrorMessage(`Task Storage ${label} failed: ${message}`);
      }
    } finally {
      this.inFlight = false;
    }
  }
}
