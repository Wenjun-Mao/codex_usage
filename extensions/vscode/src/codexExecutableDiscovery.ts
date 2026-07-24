import * as path from "path";

export type CodexExecutableSource = "cli-override" | "official-vscode-extension" | "desktop-app" | "path";

export type CodexExecutableCandidate = {
  executablePath: string;
  source: CodexExecutableSource;
};

export type CodexExecutableDiscoveryContext = {
  platform: NodeJS.Platform;
  arch: string;
  env: NodeJS.ProcessEnv;
  homeDir: string;
  cliOverride?: string;
  officialExtensionPath?: string;
};

export type CodexExecutableDiscoveryProbe = {
  pathExists(candidate: string): Promise<boolean>;
  listDirectoryNames(directory: string): Promise<string[]>;
  windowsAppxInstallLocation(): Promise<string | undefined>;
};

export async function discoverCodexExecutableCandidates(
  context: CodexExecutableDiscoveryContext,
  probe: CodexExecutableDiscoveryProbe,
): Promise<CodexExecutableCandidate[]> {
  assertSupportedPlatform(context);

  const candidates: CodexExecutableCandidate[] = [];
  const seen = new Set<string>();
  const addCandidate = (executablePath: string, source: CodexExecutableSource): void => {
    const key = candidateKey(context.platform, executablePath);
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    candidates.push({ executablePath, source });
  };
  const addExistingCandidate = async (executablePath: string, source: CodexExecutableSource): Promise<void> => {
    if (await pathExists(probe, executablePath)) {
      addCandidate(executablePath, source);
    }
  };

  if (context.cliOverride) {
    addCandidate(context.cliOverride, "cli-override");
  }

  if (context.officialExtensionPath) {
    const executablePath = extensionExecutablePath(context);
    await addExistingCandidate(executablePath, "official-vscode-extension");
  }

  if (context.platform === "darwin") {
    await addExistingCandidate("/Applications/ChatGPT.app/Contents/Resources/codex", "desktop-app");
    await addExistingCandidate(
      path.posix.join(context.homeDir, "Applications", "ChatGPT.app", "Contents", "Resources", "codex"),
      "desktop-app",
    );
  } else {
    await discoverWindowsDesktopCandidates(context, probe, addExistingCandidate);
  }

  addCandidate(context.platform === "win32" ? "codex.exe" : "codex", "path");
  return candidates;
}

function assertSupportedPlatform(context: CodexExecutableDiscoveryContext): void {
  if ((context.platform === "darwin" && context.arch === "arm64") || (context.platform === "win32" && context.arch === "x64")) {
    return;
  }
  throw new Error(`Unsupported Codex executable discovery platform: ${context.platform} ${context.arch}`);
}

function extensionExecutablePath(context: CodexExecutableDiscoveryContext): string {
  if (!context.officialExtensionPath) {
    throw new Error("Official extension path is required to construct its Codex executable path");
  }
  return context.platform === "win32"
    ? path.win32.join(context.officialExtensionPath, "bin", "windows-x86_64", "codex.exe")
    : path.posix.join(context.officialExtensionPath, "bin", "macos-aarch64", "codex");
}

async function discoverWindowsDesktopCandidates(
  context: CodexExecutableDiscoveryContext,
  probe: CodexExecutableDiscoveryProbe,
  addExistingCandidate: (executablePath: string, source: CodexExecutableSource) => Promise<void>,
): Promise<void> {
  const localAppData = context.env.LOCALAPPDATA;
  const roots = localAppData
    ? [
        path.win32.join(localAppData, "OpenAI", "Codex", "bin"),
        path.win32.join(
          localAppData,
          "Packages",
          "OpenAI.Codex_2p2nqsd0c76g0",
          "LocalCache",
          "Local",
          "OpenAI",
          "Codex",
          "bin",
        ),
      ]
    : [];

  for (const root of roots) {
    await addExistingCandidate(path.win32.join(root, "codex.exe"), "desktop-app");
    for (const childName of await directoryNames(probe, root)) {
      await addExistingCandidate(path.win32.join(root, childName, "codex.exe"), "desktop-app");
    }
  }

  const appxLocation = await windowsAppxInstallLocation(probe);
  if (appxLocation) {
    await addExistingCandidate(path.win32.join(appxLocation, "app", "resources", "codex.exe"), "desktop-app");
  }
}

function candidateKey(platform: NodeJS.Platform, executablePath: string): string {
  if (!isFilesystemPath(platform, executablePath)) {
    return platform === "win32" ? `command:${executablePath.toLowerCase()}` : `command:${executablePath}`;
  }
  if (platform === "win32") {
    return `path:${path.win32.normalize(executablePath).toLowerCase()}`;
  }
  return `path:${path.posix.normalize(executablePath)}`;
}

function isFilesystemPath(platform: NodeJS.Platform, executablePath: string): boolean {
  return platform === "win32"
    ? /[\\/]/.test(executablePath) || /^[a-z]:/i.test(executablePath)
    : executablePath.includes("/");
}

async function pathExists(probe: CodexExecutableDiscoveryProbe, candidate: string): Promise<boolean> {
  try {
    return await probe.pathExists(candidate);
  } catch {
    return false;
  }
}

async function directoryNames(probe: CodexExecutableDiscoveryProbe, directory: string): Promise<string[]> {
  try {
    return (await probe.listDirectoryNames(directory)).sort();
  } catch {
    return [];
  }
}

async function windowsAppxInstallLocation(probe: CodexExecutableDiscoveryProbe): Promise<string | undefined> {
  try {
    return await probe.windowsAppxInstallLocation();
  } catch {
    return undefined;
  }
}
