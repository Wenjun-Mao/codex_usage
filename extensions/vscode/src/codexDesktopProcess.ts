import { execFile } from "child_process";
import { promisify } from "util";

export type CodexDesktopProcessState =
  | { status: "closed" }
  | { status: "running" }
  | { status: "unknown"; reason: string };

type ProcessExecutor = (
  file: string,
  args: readonly string[],
  options: { shell: false; windowsHide: true; timeout: number },
) => Promise<{ stdout: string }>;

export type CodexDesktopProcessDependencies = {
  platform: NodeJS.Platform;
  executeFile: ProcessExecutor;
};

const executeFile = promisify(execFile);
const PROCESS_TIMEOUT_MS = 5_000;
const WINDOWS_PROCESS_COMMAND = [
  "-NoProfile",
  "-NonInteractive",
  "-Command",
  "@(Get-Process -Name ChatGPT,OpenAI.Codex -ErrorAction SilentlyContinue).Count",
] as const;

export async function inspectCodexDesktopProcess(
  overrides: Partial<CodexDesktopProcessDependencies> = {},
): Promise<CodexDesktopProcessState> {
  const dependencies: CodexDesktopProcessDependencies = {
    platform: process.platform,
    executeFile: defaultProcessExecutor,
    ...overrides,
  };

  try {
    if (dependencies.platform === "darwin") {
      const result = await dependencies.executeFile(
        "/bin/ps",
        ["-axo", "pid=,args="],
        processOptions(),
      );
      return macosDesktopRunning(result.stdout)
        ? { status: "running" }
        : { status: "closed" };
    }
    if (dependencies.platform === "win32") {
      const result = await dependencies.executeFile(
        "powershell.exe",
        WINDOWS_PROCESS_COMMAND,
        processOptions(),
      );
      const count = Number.parseInt(result.stdout.trim(), 10);
      return Number.isSafeInteger(count) && count >= 0
        ? { status: count > 0 ? "running" : "closed" }
        : { status: "unknown", reason: "Codex Desktop process output was invalid" };
    }
    return {
      status: "unknown",
      reason: `Unsupported Codex Desktop process platform: ${dependencies.platform}`,
    };
  } catch {
    return { status: "unknown", reason: "Codex Desktop process inspection failed" };
  }
}

function macosDesktopRunning(output: string): boolean {
  return output.split(/\r?\n/).some((line) => {
    const command = line.trim().replace(/^\d+\s+/, "");
    return /(?:^|\/)ChatGPT\.app\/Contents\/MacOS\/ChatGPT(?:\s|$)/.test(command);
  });
}

function processOptions() {
  return { shell: false as const, windowsHide: true as const, timeout: PROCESS_TIMEOUT_MS };
}

async function defaultProcessExecutor(
  file: string,
  args: readonly string[],
  options: { shell: false; windowsHide: true; timeout: number },
): Promise<{ stdout: string }> {
  return executeFile(file, [...args], options);
}
