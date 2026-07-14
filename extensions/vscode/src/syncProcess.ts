import { spawn, type ChildProcessWithoutNullStreams, type SpawnOptionsWithoutStdio } from "child_process";

import {
  parseSyncProgressLine,
  parseSyncRunResult,
  type SyncProgressEvent,
  type SyncRunResult,
} from "./syncProtocol";

type SpawnProcess = (
  executablePath: string,
  args: string[],
  options: SpawnOptionsWithoutStdio,
) => ChildProcessWithoutNullStreams;

export type RunSyncProcessOptions = {
  executablePath: string;
  args: string[];
  env: NodeJS.ProcessEnv;
  onProgress: (event: SyncProgressEvent) => void;
  onOutput: (text: string) => void;
  spawnProcess?: SpawnProcess;
};

export type SyncProcessCompletion = {
  exitCode: number | null;
  result: SyncRunResult;
  stdout: string;
  stderr: string;
};

export function runSyncProcess(options: RunSyncProcessOptions): Promise<SyncProcessCompletion> {
  const spawnProcess = options.spawnProcess ?? spawn;

  return new Promise((resolve, reject) => {
    const child = spawnProcess(options.executablePath, options.args, {
      shell: false,
      windowsHide: true,
      env: options.env,
    });
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");

    let stdout = "";
    let stderr = "";
    let stderrLineBuffer = "";
    let closeSeen = false;
    let exitCode: number | null = null;
    let stdoutEnded = false;
    let stderrEnded = false;
    let settled = false;

    const rejectOnce = (error: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      reject(error);
    };

    const emitProgressLine = (line: string): void => {
      const progress = parseSyncProgressLine(line.endsWith("\r") ? line.slice(0, -1) : line);
      if (progress) {
        options.onProgress(progress);
      }
    };

    const consumeStderrLines = (text: string): void => {
      stderrLineBuffer += text;
      let newlineIndex = stderrLineBuffer.indexOf("\n");
      while (newlineIndex >= 0) {
        emitProgressLine(stderrLineBuffer.slice(0, newlineIndex));
        stderrLineBuffer = stderrLineBuffer.slice(newlineIndex + 1);
        newlineIndex = stderrLineBuffer.indexOf("\n");
      }
    };

    const settleAfterStreams = (): void => {
      if (settled || !closeSeen || !stdoutEnded || !stderrEnded) {
        return;
      }

      try {
        const result = parseSyncRunResult(stdout);
        settled = true;
        resolve({ exitCode, result, stdout, stderr });
      } catch (error) {
        if (exitCode === 0) {
          rejectOnce(error instanceof Error ? error : new Error(String(error)));
          return;
        }
        const details = stderr.trim() || stdout.trim() || `codex-usage exited with code ${exitCode}`;
        rejectOnce(new Error(details));
      }
    };

    child.stdout.on("error", rejectOnce);
    child.stdout.on("data", (text: string) => {
      stdout += text;
      options.onOutput(text);
    });
    child.stdout.on("end", () => {
      stdoutEnded = true;
      settleAfterStreams();
    });
    child.stderr.on("error", rejectOnce);
    child.stderr.on("data", (text: string) => {
      stderr += text;
      options.onOutput(text);
      consumeStderrLines(text);
    });
    child.stderr.on("end", () => {
      if (stderrLineBuffer) {
        emitProgressLine(stderrLineBuffer);
        stderrLineBuffer = "";
      }
      stderrEnded = true;
      settleAfterStreams();
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        rejectOnce(new Error(`Could not start bundled codex-usage executable: ${options.executablePath}`));
        return;
      }
      rejectOnce(error);
    });
    child.on("close", (code) => {
      closeSeen = true;
      exitCode = code;
      settleAfterStreams();
    });
  });
}
