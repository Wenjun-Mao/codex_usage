import {
  spawn,
  type ChildProcessWithoutNullStreams,
} from "child_process";

export type CodexProcessCleanupOptions = {
  cleanupGraceTimeoutMs?: number;
  cleanupForceTimeoutMs?: number;
};

const DEFAULT_CLEANUP_GRACE_TIMEOUT_MS = 250;
const DEFAULT_CLEANUP_FORCE_TIMEOUT_MS = 1_000;
const GROUP_POLL_INTERVAL_MS = 10;

export async function closeCodexProcessTree(
  child: ChildProcessWithoutNullStreams,
  options: CodexProcessCleanupOptions,
): Promise<void> {
  const close = observeClose(child);
  const processGroupId =
    process.platform === "win32" || child.pid === undefined
      ? undefined
      : child.pid;
  try {
    try {
      child.stdin.end();
    } catch {
      // Termination still proceeds when stdin has already failed.
    }
    terminateGracefully(child, processGroupId);
    const graceTimeout = positiveInteger(
      options.cleanupGraceTimeoutMs,
      DEFAULT_CLEANUP_GRACE_TIMEOUT_MS,
    );
    const closedGracefully = await close.wait(graceTimeout);
    if (closedGracefully && !processGroupExists(processGroupId)) {
      return;
    }

    const forceTimeout = positiveInteger(
      options.cleanupForceTimeoutMs,
      DEFAULT_CLEANUP_FORCE_TIMEOUT_MS,
    );
    await forceProcessTree(child, processGroupId, forceTimeout);
    await Promise.all([
      close.wait(forceTimeout),
      waitForProcessGroupExit(processGroupId, forceTimeout),
    ]);
  } finally {
    close.dispose();
  }
}

function terminateGracefully(
  child: ChildProcessWithoutNullStreams,
  processGroupId: number | undefined,
): void {
  if (signalProcessGroup(processGroupId, "SIGTERM")) {
    return;
  }
  try {
    child.kill();
  } catch {
    // Forced cleanup below remains authoritative.
  }
}

async function forceProcessTree(
  child: ChildProcessWithoutNullStreams,
  processGroupId: number | undefined,
  timeoutMs: number,
): Promise<void> {
  if (process.platform === "win32" && child.pid !== undefined) {
    await runWindowsTaskkill(child.pid, timeoutMs);
  } else if (signalProcessGroup(processGroupId, "SIGKILL")) {
    return;
  }
  try {
    child.kill("SIGKILL");
  } catch {
    // Cleanup remains bounded even when the operating system denies termination.
  }
}

function signalProcessGroup(
  processGroupId: number | undefined,
  signal: NodeJS.Signals,
): boolean {
  if (processGroupId === undefined) {
    return false;
  }
  try {
    process.kill(-processGroupId, signal);
    return true;
  } catch (error) {
    return isMissingProcess(error);
  }
}

function processGroupExists(processGroupId: number | undefined): boolean {
  if (processGroupId === undefined) {
    return false;
  }
  try {
    process.kill(-processGroupId, 0);
    return true;
  } catch (error) {
    if (isMissingProcess(error)) {
      return false;
    }
    return true;
  }
}

async function waitForProcessGroupExit(
  processGroupId: number | undefined,
  timeoutMs: number,
): Promise<void> {
  if (processGroupId === undefined) {
    return;
  }
  const deadline = Date.now() + timeoutMs;
  while (processGroupExists(processGroupId) && Date.now() < deadline) {
    await delay(Math.min(GROUP_POLL_INTERVAL_MS, deadline - Date.now()));
  }
}

function observeClose(child: ChildProcessWithoutNullStreams): {
  wait(timeoutMs: number): Promise<boolean>;
  dispose(): void;
} {
  let closed = false;
  let resolveClose: (() => void) | undefined;
  const closePromise = new Promise<void>((resolve) => {
    resolveClose = resolve;
  });
  const onClose = (): void => {
    closed = true;
    resolveClose?.();
  };
  const onError = (): void => {
    // Keep the process error observed while the close deadline remains authoritative.
  };
  child.once("close", onClose);
  child.on("error", onError);
  return {
    async wait(timeoutMs) {
      if (closed) {
        return true;
      }
      let timer: NodeJS.Timeout | undefined;
      const timedOut = new Promise<false>((resolve) => {
        timer = setTimeout(() => resolve(false), timeoutMs);
      });
      const result = await Promise.race([
        closePromise.then(() => true as const),
        timedOut,
      ]);
      if (timer) {
        clearTimeout(timer);
      }
      return result;
    },
    dispose() {
      child.removeListener("close", onClose);
      child.removeListener("error", onError);
    },
  };
}

function runWindowsTaskkill(pid: number, timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    const killer = spawn(
      "taskkill.exe",
      ["/PID", String(pid), "/T", "/F"],
      {
        shell: false,
        stdio: "ignore",
        windowsHide: true,
      },
    );
    const timer = setTimeout(() => {
      try {
        killer.kill();
      } catch {
        // The bounded taskkill attempt has already settled.
      }
      resolve();
    }, timeoutMs);
    const settle = (): void => {
      clearTimeout(timer);
      resolve();
    };
    killer.once("error", settle);
    killer.once("close", settle);
  });
}

function isMissingProcess(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ESRCH"
  );
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, milliseconds)));
}
