import { spawn as spawnChild, type ChildProcess, type SpawnOptions } from "child_process";
import * as path from "path";
import { AgentClient, AgentUnavailableError, samePath } from "./agentClient";

const STARTUP_ATTEMPTS = 80;
const STARTUP_RETRY_MS = 125;

interface LedgerIdentity {
  codex_home: string;
  ledger_revision: number;
}

interface CaptureOutcome {
  outcome: string;
  error?: string;
}

export interface AgentSupervisorOptions {
  settingsFile: string;
  getCodexHome: () => Promise<string>;
  resolveExecutable: () => Promise<string>;
  parentPid?: number;
  discover?: (codexHome: string) => Promise<AgentClient>;
  spawn?: (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;
  sleep?: (milliseconds: number) => Promise<void>;
}

export interface LegacyServiceStatus {
  supported: boolean;
  installed: boolean;
  recognized: boolean;
  detail: string;
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
  private startingHome: string | undefined;

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
      if (this.managedClient?.isSameAgent(client)) this.managedClient = client;
      return client;
    } catch (error) {
      if (!(error instanceof AgentUnavailableError)) throw error;
    }
    if (this.starting) {
      if (this.startingHome === undefined || !samePath(this.startingHome, codexHome)) {
        throw new Error("The collector is still starting for another CODEX_HOME.");
      }
      return this.starting;
    }
    this.startingHome = codexHome;
    this.starting = this.startTransientAgent(codexHome).finally(() => {
      this.starting = undefined;
      this.startingHome = undefined;
    });
    return this.starting;
  }

  async configureCodexHome(codexHome: string): Promise<AgentClient> {
    const target = path.resolve(codexHome.trim());
    if (!codexHome.trim()) throw new Error("Choose a CODEX_HOME folder first.");
    if (this.starting && (this.startingHome === undefined || !samePath(this.startingHome, target))) {
      throw new Error("Wait for the current collector startup before changing CODEX_HOME.");
    }
    const current = await this.codexHome();
    if (samePath(current, target)) return this.acquire();
    await this.stopOrRejectCurrentCollector(current);
    await this.runControl(["--set-codex-home", target]);
    return this.acquire();
  }

  async currentCodexHome(): Promise<string> {
    return this.codexHome();
  }

  async legacyServiceStatus(): Promise<LegacyServiceStatus> {
    const status = await this.runControlJson<LegacyServiceStatus>(["--service-status"]);
    if (typeof status?.installed !== "boolean" || typeof status.recognized !== "boolean"
      || typeof status.supported !== "boolean" || typeof status.detail !== "string") {
      throw new Error("The bundled collector returned an invalid service status.");
    }
    return status;
  }

  async handoffLegacyService(): Promise<{ ledgerRevision: number; codexHome: string }> {
    const home = await this.codexHome();
    if (this.starting) {
      if (!samePath(this.startingHome ?? "", home)) {
        throw new Error("The collector is still starting for another CODEX_HOME.");
      }
      await this.starting;
    }
    const registration = await this.legacyServiceStatus();
    if (!registration.installed || !registration.recognized) {
      throw new Error("No recognized Codex Usage background service is registered. Nothing was changed.");
    }
    let previous: AgentClient | undefined;
    try {
      previous = await this.discover(home);
    } catch (error) {
      if (!(error instanceof AgentUnavailableError)) throw error;
    }
    const alreadyOwned = previous !== undefined && this.isManagedClient(home, previous);
    if (previous && previous.processOwner !== "background" && !alreadyOwned) {
      throw new Error("The active collector belongs to another client. Close that client before handoff.");
    }
    const revision = previous ? (await this.ledgerIdentity(previous, home)).ledger_revision : 0;
    await this.runControl(["--uninstall-service"]);
    const afterRemoval = await this.legacyServiceStatus();
    if (afterRemoval.installed) {
      throw new Error("The service is still registered. Check the Codex Usage output and retry handoff.");
    }
    if (previous && !alreadyOwned) await this.waitForAgentExit(home, previous);
    const client = alreadyOwned ? await this.discover(home) : await this.startTransientAgent(home);
    if ((alreadyOwned && !previous?.isSameAgent(client)) || !this.isManagedClient(home, client)) {
      throw new Error("A different collector acquired the ledger. Close it, then retry handoff.");
    }
    const beforeCapture = await this.ledgerIdentity(client, home);
    if (beforeCapture.ledger_revision < revision) {
      throw new Error("Ledger revision decreased during handoff. Stop and inspect the selected CODEX_HOME.");
    }
    const capture = await client.post<CaptureOutcome>("/v1/capture");
    if (capture.outcome !== "success") {
      throw new Error(`The first VS Code capture failed: ${capture.error || capture.outcome || "unknown outcome"}.`);
    }
    const afterCapture = await this.ledgerIdentity(client, home);
    if (afterCapture.ledger_revision < beforeCapture.ledger_revision) {
      throw new Error("Ledger revision decreased after capture. Stop and inspect the selected CODEX_HOME.");
    }
    return { ledgerRevision: afterCapture.ledger_revision, codexHome: home };
  }

  private async ledgerIdentity(client: AgentClient, home: string): Promise<LedgerIdentity> {
    const status = await client.get<LedgerIdentity>("/v1/status");
    if (typeof status?.codex_home !== "string" || !samePath(status.codex_home, home)
      || !Number.isSafeInteger(status.ledger_revision) || status.ledger_revision < 0) {
      throw new Error("The collector status does not match the selected CODEX_HOME and ledger.");
    }
    return status;
  }

  async stopManagedAgent(): Promise<boolean> {
    const client = this.managedClient;
    const home = this.managedHome;
    this.managedClient = undefined;
    this.managedHome = undefined;
    if (!client || !home) return false;
    try {
      const current = await this.discover(home);
      if (!client.isSameAgent(current) || !current.isTransientOwnedBy(this.parentPid, client.processId)) {
        return false;
      }
      try {
        await current.post("/v1/shutdown");
      } catch (error) {
        if (!(error instanceof AgentUnavailableError)) throw error;
      }
      await this.waitForStop(home);
      return true;
    } catch (error) {
      if (error instanceof AgentUnavailableError) return true;
      throw error;
    }
  }

  private async startTransientAgent(codexHome: string): Promise<AgentClient> {
    // The control command validates the shared home before the long-running
    // process can claim the writer lock.
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
    const client = await this.waitForClient(codexHome, () => launchError);
    if (client.isTransientOwnedBy(this.parentPid, child.pid)) {
      this.managedHome = codexHome;
      this.managedClient = client;
    }
    return client;
  }

  private async stopOrRejectCurrentCollector(codexHome: string): Promise<void> {
    let active: AgentClient;
    try {
      active = await this.discover(codexHome);
    } catch (error) {
      if (error instanceof AgentUnavailableError) return;
      throw error;
    }
    if (!this.isManagedClient(codexHome, active)) {
      throw new Error(
        "Another client owns the active collector. Stop it from its owning client before changing CODEX_HOME.",
      );
    }
    if (!await this.stopManagedAgent()) {
      throw new Error("The collector ownership changed before CODEX_HOME could be updated.");
    }
  }

  private isManagedClient(codexHome: string, client: AgentClient): boolean {
    return this.managedHome !== undefined
      && this.managedClient !== undefined
      && samePath(this.managedHome, codexHome)
      && this.managedClient.isSameAgent(client)
      && client.isTransientOwnedBy(this.parentPid, this.managedClient.processId);
  }

  private async runControl(control: readonly string[]): Promise<string> {
    const executable = await this.options.resolveExecutable();
    const child = this.spawn(executable, ["--settings-file", this.options.settingsFile, ...control], {
      detached: false,
      stdio: "pipe",
      windowsHide: true,
    });
    const result = await waitForExit(child);
    if (result.code !== 0) {
      throw new Error(result.stderr || `The bundled collector exited with code ${result.code ?? "unknown"}.`);
    }
    return result.stdout;
  }

  private async runControlJson<T>(control: readonly string[]): Promise<T> {
    const output = await this.runControl(control);
    try {
      return JSON.parse(output) as T;
    } catch {
      throw new Error("The bundled collector returned an invalid service status.");
    }
  }

  private async waitForAgentExit(codexHome: string, previous: AgentClient): Promise<void> {
    for (let attempt = 0; attempt < STARTUP_ATTEMPTS; attempt += 1) {
      try {
        const current = await this.discover(codexHome);
        if (!previous.isSameAgent(current)) {
          throw new Error("Another collector acquired the ledger during handoff. Close it and retry.");
        }
      } catch (error) {
        if (error instanceof AgentUnavailableError) return;
        throw error;
      }
      await this.sleep(STARTUP_RETRY_MS);
    }
    throw new Error("The legacy collector is still running. Quit the native app or stop its process, then reopen the dashboard to start VS Code capture.");
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

  private async waitForStop(codexHome: string): Promise<void> {
    for (let attempt = 0; attempt < STARTUP_ATTEMPTS; attempt += 1) {
      try {
        await this.discover(codexHome);
      } catch (error) {
        if (error instanceof AgentUnavailableError) return;
        throw error;
      }
      await this.sleep(STARTUP_RETRY_MS);
    }
    throw new Error("The owned collector did not stop before changing CODEX_HOME.");
  }

  private async codexHome(): Promise<string> {
    const value = (await this.options.getCodexHome()).trim();
    if (!value) throw new Error("Choose a CODEX_HOME folder before starting Codex Usage.");
    return path.resolve(value);
  }
}

function waitForExit(child: ChildProcess): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      stdout = `${stdout}${chunk.toString("utf8")}`.slice(-8_192);
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr = `${stderr}${chunk.toString("utf8")}`.slice(-8_192);
    });
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, stdout: stdout.trim(), stderr: stderr.trim() }));
  });
}
