import * as fs from "fs/promises";
import * as path from "path";

export type SupportedAgentTarget = "darwin-arm64" | "win32-x64";

export function supportedAgentTarget(
  platform: NodeJS.Platform = process.platform,
  architecture: string = process.arch,
): SupportedAgentTarget {
  if (platform === "darwin" && architecture === "arm64") return "darwin-arm64";
  if (platform === "win32" && architecture === "x64") return "win32-x64";
  throw new Error(
    "Codex Usage supports the bundled collector on macOS Apple Silicon and Windows x64 only.",
  );
}

export function bundledAgentRelativePath(
  platform: NodeJS.Platform = process.platform,
  architecture: string = process.arch,
): string {
  const target = supportedAgentTarget(platform, architecture);
  return target === "darwin-arm64"
    ? path.join("bin", target, "codex-usage-agent")
    : path.join("bin", target, "codex-usage-agent.exe");
}

export async function resolveBundledAgent(
  extensionPath: string,
  platform: NodeJS.Platform = process.platform,
  architecture: string = process.arch,
): Promise<string> {
  const executablePath = path.join(extensionPath, bundledAgentRelativePath(platform, architecture));
  try {
    await fs.access(executablePath);
    return executablePath;
  } catch {
    throw new Error(
      `The ${supportedAgentTarget(platform, architecture)} Codex Usage collector is missing from this VSIX. Reinstall the platform-specific extension package.`,
    );
  }
}
