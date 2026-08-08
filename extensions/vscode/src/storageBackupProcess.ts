import { spawn, type ChildProcessWithoutNullStreams, type SpawnOptionsWithoutStdio } from "child_process";

import { closeCodexProcessTree } from "./codexProcessCleanup";
import {
  parseBackupProgressLine,
  parseBackupResult,
  type BackupProgress,
  type BackupResult,
} from "./storageBackupProtocol";

type SpawnProcess = (
  executablePath: string,
  args: string[],
  options: SpawnOptionsWithoutStdio,
) => ChildProcessWithoutNullStreams;

export class BackupCancelledError extends Error {
  constructor() {
    super("Task backup was cancelled.");
    this.name = "BackupCancelledError";
  }
}

export type RunBackupProcessOptions = {
  executablePath: string;
  args: string[];
  env: NodeJS.ProcessEnv;
  cancellationToken: { isCancellationRequested: boolean; onCancellationRequested(listener: () => void): { dispose(): void } };
  onProgress(event: BackupProgress): void;
  onOutput(text: string): void;
  spawnProcess?: SpawnProcess;
};

export function runBackupProcess(options: RunBackupProcessOptions): Promise<BackupResult> {
  return runStorageOperation({
    ...options,
    parseProgressLine: parseBackupProgressLine,
    parseResult: parseBackupResult,
  });
}

export type RunStorageOperationOptions<Result, Progress> = {
  executablePath: string;
  args: string[];
  env: NodeJS.ProcessEnv;
  cancellationToken: { isCancellationRequested: boolean; onCancellationRequested(listener: () => void): { dispose(): void } };
  onProgress(event: Progress): void;
  onOutput(text: string): void;
  parseProgressLine(line: string): Progress | undefined;
  parseResult(stdout: string): Result;
  spawnProcess?: SpawnProcess;
};

export function runStorageOperation<Result, Progress>(
  options: RunStorageOperationOptions<Result, Progress>,
): Promise<Result> {
  const spawnProcess = options.spawnProcess ?? spawn;
  return new Promise((resolve, reject) => {
    const child = spawnProcess(options.executablePath, options.args, {
      shell: false,
      windowsHide: true,
      env: options.env,
      detached: process.platform !== "win32",
    });
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    let stdout = "";
    let stderr = "";
    let stderrLines = "";
    let settled = false;
    let cancelled = false;

    const settle = (callback: () => void): void => {
      if (!settled) {
        settled = true;
        cancellation.dispose();
        callback();
      }
    };
    const cancel = (): void => {
      if (cancelled || settled) {
        return;
      }
      cancelled = true;
      void closeCodexProcessTree(child, {}).finally(() => {
        settle(() => reject(new BackupCancelledError()));
      });
    };
    const cancellation = options.cancellationToken.onCancellationRequested(cancel);
    if (options.cancellationToken.isCancellationRequested) {
      cancel();
      return;
    }
    const consumeProgress = (text: string): void => {
      stderrLines += text;
      let next = stderrLines.indexOf("\n");
      while (next >= 0) {
        const line = stderrLines.slice(0, next).replace(/\r$/, "");
        const progress = options.parseProgressLine(line);
        if (progress) {
          options.onProgress(progress);
        } else if (line.trim()) {
          options.onOutput(`${line}\n`);
        }
        stderrLines = stderrLines.slice(next + 1);
        next = stderrLines.indexOf("\n");
      }
    };

    child.stdout.on("data", (text: string) => {
      stdout += text;
      options.onOutput(text);
    });
    child.stderr.on("data", (text: string) => {
      stderr += text;
      consumeProgress(text);
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      if (cancelled) {
        return;
      }
      settle(() => reject(error.code === "ENOENT"
        ? new Error(`Could not start bundled codex-usage executable: ${options.executablePath}`)
        : error));
    });
    child.on("close", (code) => {
      if (cancelled) {
        return;
      }
      if (stderrLines) {
        const progress = options.parseProgressLine(stderrLines.replace(/\r$/, ""));
        if (progress) {
          options.onProgress(progress);
        } else if (stderrLines.trim()) {
          options.onOutput(stderrLines);
        }
      }
      if (code !== 0) {
        settle(() => reject(new Error(stderr.trim() || stdout.trim() || `codex-usage exited with code ${code}`)));
        return;
      }
      try {
        const result = options.parseResult(stdout);
        settle(() => resolve(result));
      } catch (error) {
        settle(() => reject(error instanceof Error ? error : new Error(String(error))));
      }
    });
  });
}
