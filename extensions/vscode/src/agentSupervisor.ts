import { spawn as spawnChild, type ChildProcess, type SpawnOptions } from "child_process";
import * as path from "path";
import { AgentClient, AgentUnavailableError } from "./agentClient";

const STARTUP_ATTEMPTS = 80;
const STARTUP_RETRY_MS = 125;

export interface AgentSupervisorOptions {
  settingsFile: string;
  getCodexHome: () => Promise<string>;
  setCodexHome: (codexHome: string) => Promise<void>;
  resolveExecutable: () => Promise<string>;
  parentPid?: number;
  discover?: (codexHome: string) => Promise<AgentClient>;
  spawn?: (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;
  sleep?: (milliseconds: number) => Promise<void>;
}

/**
 * Owns only the transient collector it starts. The collector itself owns the
 * cross-process lock, so a stale descriptor can never make VS Code create a
 * second ledger writer.
 */
export class AgentSupervisor {
  private readonly discover: (codexHome: string) => Promise<AgentClient>;
  private readonly spawn: (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;
  private readonly sleep: (milliseconds: number) => Promise<void>;
  private readonly parentPid: number;
  private managedHome: string | undefined;
  private managedClient: AgentClient | undefined;
  private starting: Promise<AgentClient> | undefined;

  constructor(private readonly options: AgentSupervisorOptions) {
    this.discover = options.discover ?? AgentClient.discoverAt;
    this.spawn = options.spawn ?? ((command, args, spawnOptions) => spawnChild(command, args, spawnOptions));
    this.sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
    this.parentPid = options.parentPid ?? process.pid;
  }

  async acquire(): Promise<AgentClient> {
    const codexHome = await this.codexHome();
    try {
      const client = await this.discover(codexHome);
      if (this.managedHome === codexHome) this.managedClient = client;
      return client;
    } catch (error) {
      if (!(error instanceof AgentUnavailableError)) throw error;
    }
    if (!this.starting) {
      this.starting = this.startTransientAgent(codexHome).finally(() => {
        this.starting = undefined;
      });
    }
    return this.starting;
  }

  async configureCodexHome(codexHome: string): Promise<AgentClient> {
    const target = path.resolve(codexHome.trim());
    if (!codexHome.trim()) throw new Error("Choose a CODEX_HOME folder first.");
    await this.runControl(["--set-codex-home", target]);
    if (this.managedHome && this.managedHome !== target) await this.stopManagedAgent();
    await this.options.setCodexHome(target);
    return this.acquire();
  }

  async currentCodexHome(): Promise<string> {
    return this.codexHome();
  }

  async stopManagedAgent(): Promise<void> {
    const client = this.managedClient;
    this.managedClient = undefined;
    this.managedHome = undefined;
    if (!client) return;
    try {
      await client.post("/v1/shutdown");
    } catch {
      // A parent-bound agent may already be stopping while VS Code reloads.
    }
  }

  private async startTransientAgent(codexHome: string): Promise<AgentClient> {
    // The control command validates the selected home and writes extension-owned
    // settings before the long-running process can claim the writer lock.
    await this.runControl(["--set-codex-home", codexHome]);
    const executable = await this.options.resolveExecutable();
    let launchError: Error | undefined;
    const child = this.spawn(executable, [
      "--settings-file", this.options.settingsFile,
      "--parent-pid", String(this.parentPid),
    ], {
      detached: false,
      stdio: "ignore",
      windowsHide: true,
    });
    child.once("error", (error) => {
      launchError = error instanceof Error ? error : new Error(String(error));
    });
    child.unref();
    this.managedHome = codexHome;
    const client = await this.waitForClient(codexHome, () => launchError);
    this.managedClient = client;
    return client;
  }

  private async runControl(control: readonly string[]): Promise<void> {
    const executable = await this.options.resolveExecutable();
    const child = this.spawn(executable, ["--settings-file", this.options.settingsFile, ...control], {
      detached: false,
      stdio: "pipe",
      windowsHide: true,
    });
    const stderr = await waitForExit(child);
    if (stderr.code !== 0) {
      throw new Error(stderr.text || `The bundled collector exited with code ${stderr.code ?? "unknown"}.`);
    }
  }

  private async waitForClient(
    codexHome: string,
    launchError: () => Error | undefined,
  ): Promise<AgentClient> {
    let latest = "Collector startup timed out.";
    for (let attempt = 0; attempt < STARTUP_ATTEMPTS; attempt += 1) {
      const error = launchError();
      if (error) throw new Error(`Could not start the bundled collector: ${error.message}`);
      try {
        return await this.discover(codexHome);
      } catch (cause) {
        latest = cause instanceof Error ? cause.message : String(cause);
        if (!(cause instanceof AgentUnavailableError)) throw cause;
      }
      await this.sleep(STARTUP_RETRY_MS);
    }
    throw new Error(`The bundled collector did not become ready: ${latest}`);
  }

  private async codexHome(): Promise<string> {
    const value = (await this.options.getCodexHome()).trim();
    if (!value) throw new Error("Choose a CODEX_HOME folder before starting Codex Usage.");
    return path.resolve(value);
  }
}

function waitForExit(child: ChildProcess): Promise<{ code: number | null; text: string }> {
  return new Promise((resolve, reject) => {
    let output = "";
    child.stderr?.on("data", (chunk: Buffer) => {
      output = `${output}${chunk.toString("utf8")}`.slice(-8_192);
    });
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, text: output.trim() }));
  });
}
