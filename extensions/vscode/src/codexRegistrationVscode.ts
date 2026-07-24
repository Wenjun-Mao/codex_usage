import { execFile } from "child_process";
import * as fs from "fs/promises";
import { homedir } from "os";
import { promisify } from "util";
import * as vscode from "vscode";

import {
  registerCodexTasks,
  type CodexAppServerOptions,
  type CodexTaskRegistrationResult,
} from "./codexAppServer";
import {
  discoverCodexExecutableCandidates,
  type CodexExecutableDiscoveryContext,
  type CodexExecutableDiscoveryProbe,
} from "./codexExecutableDiscovery";

const APPX_COMMAND = [
  "-NoProfile",
  "-NonInteractive",
  "-Command",
  "(Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1 -ExpandProperty InstallLocation)",
] as const;

type FileStat = { isFile(): boolean };
type DirectoryEntry = { name: string; isDirectory(): boolean };
type PowerShellOptions = { shell: false; windowsHide: true };
type PowerShellExecutor = (
  file: string,
  args: readonly string[],
  options: PowerShellOptions,
) => Promise<{ stdout: string }>;

type RegistrarDependencies = {
  platform: NodeJS.Platform;
  arch: string;
  env: NodeJS.ProcessEnv;
  homeDir(): string;
  stat(candidate: string): Promise<FileStat>;
  readdir(directory: string, options: { withFileTypes: true }): Promise<DirectoryEntry[]>;
  executeFile: PowerShellExecutor;
  discoverCandidates: typeof discoverCodexExecutableCandidates;
  registerTasks(options: CodexAppServerOptions): Promise<CodexTaskRegistrationResult>;
};

export type CreateCodexTaskRegistrarOptions = {
  extensionVersion: string;
  dependencies?: Partial<RegistrarDependencies>;
};

export type CodexTaskRegistrar = (
  threadIds: readonly string[],
) => Promise<CodexTaskRegistrationResult>;

const executeFile = promisify(execFile);

export function createCodexTaskRegistrar(options: CreateCodexTaskRegistrarOptions): CodexTaskRegistrar {
  const dependencies: RegistrarDependencies = {
    platform: process.platform,
    arch: process.arch,
    env: process.env,
    homeDir: homedir,
    stat: fs.stat,
    readdir: fs.readdir,
    executeFile: defaultPowerShellExecutor,
    discoverCandidates: discoverCodexExecutableCandidates,
    registerTasks: registerCodexTasks,
    ...options.dependencies,
  };

  return async (threadIds) => {
    const configuration = vscode.workspace.getConfiguration("chatgpt");
    const cliOverride = configuration.get<string>("cliExecutable");
    const officialExtensionPath = vscode.extensions.getExtension("openai.chatgpt")?.extensionPath;
    const candidates = await dependencies.discoverCandidates(
      discoveryContext(dependencies, cliOverride, officialExtensionPath),
      createDiscoveryProbe(dependencies),
    );
    return dependencies.registerTasks({
      candidates,
      threadIds,
      extensionVersion: options.extensionVersion,
    });
  };
}

function discoveryContext(
  dependencies: RegistrarDependencies,
  cliOverride: string | undefined,
  officialExtensionPath: string | undefined,
): CodexExecutableDiscoveryContext {
  return {
    platform: dependencies.platform,
    arch: dependencies.arch,
    env: dependencies.env,
    homeDir: dependencies.homeDir(),
    cliOverride,
    officialExtensionPath,
  };
}

function createDiscoveryProbe(dependencies: RegistrarDependencies): CodexExecutableDiscoveryProbe {
  return {
    async pathExists(candidate) {
      try {
        return (await dependencies.stat(candidate)).isFile();
      } catch {
        return false;
      }
    },
    async listDirectoryNames(directory) {
      try {
        const entries = await dependencies.readdir(directory, { withFileTypes: true });
        return entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);
      } catch {
        return [];
      }
    },
    async windowsAppxInstallLocation() {
      if (dependencies.platform !== "win32") {
        return undefined;
      }
      try {
        const result = await dependencies.executeFile("powershell.exe", APPX_COMMAND, {
          shell: false,
          windowsHide: true,
        });
        return result.stdout.trim() || undefined;
      } catch {
        return undefined;
      }
    },
  };
}

async function defaultPowerShellExecutor(
  file: string,
  args: readonly string[],
  options: PowerShellOptions,
): Promise<{ stdout: string }> {
  return executeFile(file, [...args], options);
}
