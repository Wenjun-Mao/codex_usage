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
  if (platform === "darwin") {
    return [
      "/Applications/Codex Usage.app",
      path.join(home, "Applications", "Codex Usage.app"),
    ];
  }
  if (platform === "win32") {
    const local = environment.LOCALAPPDATA || path.join(home, "AppData", "Local");
    const installRoots = [
      path.join(local, "Codex Usage"),
      path.join(local, "Programs", "Codex Usage"),
    ];
    const executableNames = ["codex-usage-desktop.exe", "Codex Usage.exe"];
    return installRoots.flatMap((root) =>
      executableNames.map((name) => path.join(root, name)),
    );
  }
  return [];
}
