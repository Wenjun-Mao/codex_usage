import * as vscode from "vscode";
import type { AgentClient } from "./agentClient";
import type { AgentSupervisor } from "./agentSupervisor";
import type { AgentSettings } from "./types";
import { captureIntervalChoices, captureScheduleMessage, validateCaptureInterval } from "./setupPresentation";

export async function chooseCodexHome(agentSupervisor: AgentSupervisor, refreshStatus: (interactive: boolean) => Promise<void>): Promise<void> {
  const selected = await vscode.window.showOpenDialog({
    title: "Choose CODEX_HOME",
    openLabel: "Use CODEX_HOME",
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
  });
  const codexHome = selected?.[0]?.fsPath;
  if (!codexHome) return;
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Starting the Codex Usage collector" },
      () => agentSupervisor.configureCodexHome(codexHome),
    );
    await refreshStatus(false);
    void vscode.window.showInformationMessage(
      "Codex Usage is ready. Scheduled capture runs while VS Code is open; quota snapshots missed while it is closed may not be recoverable.",
    );
  } catch (error) {
    void vscode.window.showErrorMessage(`Could not use that CODEX_HOME: ${errorMessage(error)}`);
  }
}

export async function configureCaptureInterval(client: AgentClient, refreshStatus: (interactive: boolean) => Promise<void>): Promise<void> {
  const settings = await client.get<AgentSettings>("/v1/settings");
  const selected = await vscode.window.showQuickPick(
    captureIntervalChoices(settings.capture_interval_minutes),
    { title: "Set Capture Interval", placeHolder: "Select how often to capture while VS Code is open" },
  );
  if (!selected) return;
  let interval: number | null;
  if (selected.value === "custom") {
    const entered = await vscode.window.showInputBox({
      title: "Custom Capture Interval",
      prompt: "Enter a whole number of minutes from 1 to 1,440.",
      validateInput: validateCaptureInterval,
    });
    if (entered === undefined) return;
    interval = Number(entered);
  } else {
    interval = selected.value;
  }
  await client.post<AgentSettings>("/v1/settings", {
    capture_interval_minutes: interval,
    onboarding_complete: true,
  });
  await refreshStatus(false);
  void vscode.window.showInformationMessage(captureScheduleMessage(interval));
}

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
