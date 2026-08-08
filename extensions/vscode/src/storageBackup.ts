import {
  backupFileName,
  formatStorageBytes,
  type BackupCompression,
  type BackupProgress,
  type BackupResult,
  type StorageSnapshot,
  type StorageTree,
} from "./storageBackupProtocol";
import { BackupCancelledError } from "./storageBackupProcess";

export type StorageBackupPort = {
  loadSnapshot(): Promise<StorageSnapshot>;
  chooseTree(projects: StorageSnapshot["projects"]): Promise<StorageTree | undefined>;
  chooseCompression(): Promise<BackupCompression | undefined>;
  confirmSensitiveData(tree: StorageTree, compression: BackupCompression): Promise<boolean>;
  chooseOutput(defaultFileName: string): Promise<string | undefined>;
  outputExists(path: string): Promise<boolean>;
  confirmReplace(path: string): Promise<boolean>;
  execute(request: {
    treeId: string;
    outputPath: string;
    compression: BackupCompression;
    replace: boolean;
    onProgress(event: BackupProgress): void;
  }): Promise<BackupResult>;
  reportProgress(event: BackupProgress): void;
  log(message: string): void;
  notify(kind: "info" | "warning" | "error", message: string): void;
};

export class StorageBackupController {
  private inFlight = false;

  constructor(private readonly port: StorageBackupPort) {}

  async backup(requestedTreeId?: unknown): Promise<void> {
    if (this.inFlight) {
      this.port.notify("info", "A task backup is already running. Try again when it finishes.");
      return;
    }
    this.inFlight = true;
    try {
      const snapshot = await this.port.loadSnapshot();
      const tree = await this.resolveTree(snapshot, requestedTreeId);
      if (!tree) {
        return;
      }
      const compression = await this.port.chooseCompression();
      if (!compression || !await this.port.confirmSensitiveData(tree, compression)) {
        return;
      }
      const outputPath = await this.port.chooseOutput(backupFileName(tree.title, tree.rootTaskId));
      if (!outputPath) {
        return;
      }
      const exists = await this.port.outputExists(outputPath);
      if (exists && !await this.port.confirmReplace(outputPath)) {
        return;
      }
      const result = await this.port.execute({
        treeId: tree.rootTaskId,
        outputPath,
        compression,
        replace: exists,
        onProgress: (event) => this.port.reportProgress(event),
      });
      for (const warning of result.warnings) {
        this.port.log(`[backup warning] ${warning}`);
      }
      const sizes = `${formatStorageBytes(result.sourceBytes)} to ${formatStorageBytes(result.archiveBytes)}`;
      if (result.recoveryReady) {
        this.port.notify(
          "info",
          `Verified backup created for ${tree.title || tree.rootTaskId}: ${sizes}. Archive: ${result.archivePath}. It does not delete or free Codex storage.`,
        );
      } else {
        this.port.notify(
          "warning",
          `Integrity-verified salvage backup created for ${tree.title || tree.rootTaskId}: ${sizes}. Archive: ${result.archivePath}. Review the Codex Usage output before relying on it for recovery.`,
        );
      }
      this.port.log(`[backup] archive=${result.archivePath} sha256=${result.archiveSha256} files=${result.fileCount}`);
    } catch (error) {
      if (error instanceof BackupCancelledError) {
        this.port.log("[backup] cancelled; no final archive was reported.");
        this.port.notify("info", "Task backup cancelled. No final backup archive was created.");
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      this.port.log(`[backup error] ${message}`);
      this.port.notify("error", `Task backup failed: ${message}`);
    } finally {
      this.inFlight = false;
    }
  }

  private async resolveTree(snapshot: StorageSnapshot, requestedTreeId: unknown): Promise<StorageTree | undefined> {
    if (requestedTreeId !== undefined) {
      if (typeof requestedTreeId !== "string" || !requestedTreeId.trim()) {
        this.port.notify("error", "Invalid Task Storage backup action. Refresh the dashboard and try again.");
        return undefined;
      }
      const tree = snapshot.trees.find((candidate) => candidate.rootTaskId === requestedTreeId);
      if (!tree) {
        this.port.notify("error", "This Task Storage row is no longer available. Refresh the dashboard and try again.");
      }
      return tree;
    }
    if (snapshot.projects.length === 0) {
      this.port.notify("info", "No Codex task storage is available to back up.");
      return undefined;
    }
    return this.port.chooseTree(snapshot.projects);
  }
}
