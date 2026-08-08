import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

import { runBackupProcess, BackupCancelledError } from "./storageBackupProcess";
import {
  buildStorageBackupArgs,
  buildStorageSnapshotArgs,
  formatStorageBytes,
  parseStorageSnapshot,
  type BackupCompression,
  type BackupProgress,
} from "./storageBackupProtocol";
import { chooseStorageTree } from "./storageBackupPicker";
import type { StorageBackupPort } from "./storageBackup";

type CommandResult = { stdout: string; stderr: string };

export type StorageBackupVscodeDependencies = {
  output: vscode.OutputChannel;
  resolveExecutable(): Promise<string>;
  processEnv(): NodeJS.ProcessEnv;
  runCommand(args: string[]): Promise<CommandResult>;
  runBackupProcess?: typeof runBackupProcess;
};

export function createStorageBackupVscodePort(
  dependencies: StorageBackupVscodeDependencies,
): StorageBackupPort {
  return {
    async loadSnapshot() {
      const result = await dependencies.runCommand(buildStorageSnapshotArgs());
      return parseStorageSnapshot(result.stdout);
    },
    chooseTree: chooseStorageTree,
    chooseCompression,
    confirmSensitiveData,
    chooseOutput,
    outputExists: pathExists,
    confirmReplace,
    execute: (request) => executeBackup(request, dependencies),
    reportProgress: () => undefined,
    log: (message) => dependencies.output.appendLine(message),
    notify: showMessage,
  };
}

async function chooseCompression(): Promise<BackupCompression | undefined> {
  const selected = await vscode.window.showQuickPick([
    {
      label: "Maximum",
      description: "Recommended: smallest archive, slower backup",
      detail: "Uses high zstd compression. Best for keeping long-term task backups.",
      compression: "maximum" as const,
      picked: true,
    },
    {
      label: "Balanced",
      description: "Faster backup, larger archive",
      detail: "Uses less compression when time matters more than disk space.",
      compression: "balanced" as const,
    },
  ], {
    title: "Task Backup Compression",
    placeHolder: "Choose how much to compress this task backup.",
  });
  return selected?.compression;
}

async function confirmSensitiveData(
  tree: { title: string; totalBytes: number; recoveryReady: boolean },
  compression: BackupCompression,
): Promise<boolean> {
  const label = tree.title || "this task";
  const readiness = tree.recoveryReady
    ? ""
    : " This tree has storage diagnostics, so the result will be an integrity-verified salvage backup rather than recovery-ready.";
  const selected = await vscode.window.showWarningMessage(
    `Back up ${label} (${formatStorageBytes(tree.totalBytes)}) with ${compression} compression? ` +
      "The archive can contain prompts and source code. It is compressed, not encrypted, and this does not delete or free Codex storage." +
      readiness,
    { modal: true },
    "Create Backup",
  );
  return selected === "Create Backup";
}

async function chooseOutput(defaultFileName: string): Promise<string | undefined> {
  const selected = await vscode.window.showSaveDialog({
    title: "Save Codex Task Backup",
    defaultUri: vscode.Uri.file(path.join(os.homedir(), defaultFileName)),
    saveLabel: "Create Backup",
    filters: { "Codex Task Backup": ["codex-task-backup"] },
  });
  return selected?.fsPath?.trim() || undefined;
}

async function confirmReplace(outputPath: string): Promise<boolean> {
  const selected = await vscode.window.showWarningMessage(
    `A backup already exists at ${outputPath}. Replace it only after the new archive has been fully verified?`,
    { modal: true },
    "Replace Backup",
  );
  return selected === "Replace Backup";
}

async function executeBackup(
  request: Parameters<StorageBackupPort["execute"]>[0],
  dependencies: StorageBackupVscodeDependencies,
) {
  const executablePath = await dependencies.resolveExecutable();
  const args = buildStorageBackupArgs(request);
  const runner = dependencies.runBackupProcess ?? runBackupProcess;
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Creating verified Codex task backup", cancellable: true },
    async (progress, cancellationToken) => {
      dependencies.output.appendLine(`> ${executablePath} ${args.join(" ")}`);
      let lastPercent = 0;
      try {
        return await runner({
          executablePath,
          args,
          env: dependencies.processEnv(),
          cancellationToken,
          onProgress: (event) => {
            request.onProgress(event);
            const percent = event.totalBytes > 0
              ? Math.min(100, Math.floor(event.completedBytes / event.totalBytes * 100))
              : 0;
            progress.report({
              increment: Math.max(0, percent - lastPercent),
              message: progressMessage(event),
            });
            lastPercent = Math.max(lastPercent, percent);
          },
          onOutput: (text) => dependencies.output.append(text),
        });
      } catch (error) {
        if (error instanceof BackupCancelledError) {
          dependencies.output.appendLine("[backup] cancelled; no final archive was reported.");
          throw error;
        }
        throw error;
      }
    },
  );
}

function progressMessage(event: BackupProgress): string {
  const phase = event.phase[0].toUpperCase() + event.phase.slice(1);
  const files = event.fileCount === undefined ? "" : ` | ${event.fileIndex ?? 0}/${event.fileCount} files`;
  return `${phase} ${formatStorageBytes(event.completedBytes)} of ${formatStorageBytes(event.totalBytes)}${files}`;
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await fs.stat(filePath);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

function showMessage(kind: "info" | "warning" | "error", message: string): void {
  if (kind === "info") {
    void vscode.window.showInformationMessage(message);
  } else if (kind === "warning") {
    void vscode.window.showWarningMessage(message);
  } else {
    void vscode.window.showErrorMessage(message);
  }
}
