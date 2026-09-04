import { spawn } from "child_process";
import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";

export const INSTALL_URL = "https://github.com/Wenjun-Mao/codex_usage/releases/latest";

export async function findNativeApp(
  environment: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  home: string = os.homedir(),
): Promise<string | undefined> {
  for (const candidate of nativeAppCandidates(environment, platform, home)) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  return undefined;
}

export function openNativeApp(executablePath: string): void {
  const command = process.platform === "darwin" ? "open" : executablePath;
  const args = process.platform === "darwin" ? [executablePath] : [];
  const child = spawn(command, args, { detached: true, stdio: "ignore", windowsHide: false });
  child.unref();
}

export function nativeAppCandidates(
  environment: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  home: string = os.homedir(),
): string[] {
  // Callers may inspect a target platform different from the current host.
  const targetPath = platform === "win32" ? path.win32 : path.posix;
  if (platform === "darwin") {
    return [
      "/Applications/Codex Usage.app",
      targetPath.join(home, "Applications", "Codex Usage.app"),
    ];
  }
  if (platform === "win32") {
    const local = environment.LOCALAPPDATA || targetPath.join(home, "AppData", "Local");
    const installRoots = [
      targetPath.join(local, "Codex Usage"),
      targetPath.join(local, "Programs", "Codex Usage"),
    ];
    const executableNames = ["codex-usage-desktop.exe", "Codex Usage.exe"];
    return installRoots.flatMap((root) =>
      executableNames.map((name) => targetPath.join(root, name)),
    );
  }
  return [];
}
