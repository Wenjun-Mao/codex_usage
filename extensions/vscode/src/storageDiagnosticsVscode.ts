import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

import {
  BackupCancelledError,
  runStorageOperation,
} from "./storageBackupProcess";
import {
  backupFileName,
  buildStorageAnalyzeArgs,
  buildStorageRolloverArgs,
  buildStorageSnapshotArgs,
  formatStorageBytes,
  parseAnalysisProgressLine,
  parseAnalysisResult,
  parseBackupProgressLine,
  parseRolloverResult,
  parseStorageSnapshot,
  type BackupCompression,
  type StorageTree,
} from "./storageBackupProtocol";
import { chooseStorageTree } from "./storageBackupPicker";

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

  async prepareRollover(requestedTreeId?: unknown): Promise<void> {
    await this.runExclusive("rollover", async () => {
      const tree = await this.resolveTree(requestedTreeId, {
        actionTitle: "Prepare Task Rollover",
        actionVerb: "prepare rollover for",
      });
      if (!tree) {
        return;
      }
      if (!tree.analysisComplete) {
        void vscode.window.showWarningMessage(
          "Analyze this task tree before preparing rollover.",
        );
        return;
      }
      if (!tree.canPrepareRollover) {
        void vscode.window.showInformationMessage(
          "Prepare Rollover is available for analyzed large or history-amplified task trees.",
        );
        return;
      }
      if (!tree.recoveryReady) {
        void vscode.window.showErrorMessage(
          "This task tree is not recovery-ready. Resolve its storage diagnostics before rollover.",
        );
        return;
      }
      const compression = await chooseCompression();
      if (!compression || !await confirmRollover(tree, compression)) {
        return;
      }
      const outputPath = await chooseNewOutput(
        backupFileName(tree.title, tree.rootTaskId),
      );
      if (!outputPath) {
        return;
      }
      const executablePath = await this.dependencies.resolveExecutable();
      const args = buildStorageRolloverArgs({
        treeId: tree.rootTaskId,
        outputPath,
        compression,
      });
      this.dependencies.output.appendLine(`> ${executablePath} ${args.join(" ")}`);
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "Creating verified rollover backup",
          cancellable: true,
        },
        async (progress, cancellationToken) => runStorageOperation({
          executablePath,
          args,
          env: this.dependencies.processEnv(),
          cancellationToken,
          parseProgressLine: parseBackupProgressLine,
          parseResult: parseRolloverResult,
          onProgress: (event) => progress.report({
            message: `${event.phase} | ${formatStorageBytes(event.completedBytes)} of ${formatStorageBytes(event.totalBytes)}`,
          }),
          onOutput: (text) => this.dependencies.output.append(text),
        }),
      );
      await vscode.env.clipboard.writeText(result.starterPrompt);
      this.dependencies.output.appendLine(
        `[rollover] archive=${result.backup.archivePath} sha256=${result.backup.archiveSha256} ` +
        `compression=${result.backup.compression}`,
      );
      result.checklist.forEach((item, index) => {
        this.dependencies.output.appendLine(`[rollover] ${index + 1}. ${item}`);
      });
      this.dependencies.output.show(true);
      const selected = await vscode.window.showInformationMessage(
        "Verified rollover backup created. The text-only starter prompt is on your clipboard. " +
        "Create a fresh root task in the same Codex project, verify it, and only then delete the old task in Codex.",
        "Open Backup Folder",
      );
      if (selected === "Open Backup Folder") {
        await vscode.commands.executeCommand(
          "revealFileInOS",
          vscode.Uri.file(result.backup.archivePath),
        );
      }
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
      if (error instanceof BackupCancelledError) {
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

async function chooseCompression(): Promise<BackupCompression | undefined> {
  const selected = await vscode.window.showQuickPick([
    {
      label: "Maximum",
      description: "Recommended: smallest long-term archive",
      compression: "maximum" as const,
      picked: true,
    },
    {
      label: "Balanced",
      description: "Faster backup, larger archive",
      compression: "balanced" as const,
    },
  ], {
    title: "Task Rollover Compression",
    placeHolder: "Choose compression for the recovery backup.",
  });
  return selected?.compression;
}

async function confirmRollover(
  tree: StorageTree,
  compression: BackupCompression,
): Promise<boolean> {
  const selected = await vscode.window.showWarningMessage(
    `Prepare rollover for ${tree.title || tree.rootTaskId} (${formatStorageBytes(tree.totalBytes)})? ` +
    `A new recovery-ready ${compression} backup will be created first. The plugin will not create or delete Codex tasks.`,
    { modal: true },
    "Create Backup and Prepare",
  );
  return selected === "Create Backup and Prepare";
}

async function chooseNewOutput(defaultFileName: string): Promise<string | undefined> {
  const selected = await vscode.window.showSaveDialog({
    title: "Save New Rollover Backup",
    defaultUri: vscode.Uri.file(path.join(os.homedir(), defaultFileName)),
    saveLabel: "Create New Backup",
    filters: { "Codex Task Backup": ["codex-task-backup"] },
  });
  const outputPath = selected?.fsPath?.trim();
  if (!outputPath) {
    return undefined;
  }
  try {
    await fs.stat(outputPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return outputPath;
    }
    throw error;
  }
  throw new Error("Choose a new backup file. Rollover never replaces an existing archive.");
}
