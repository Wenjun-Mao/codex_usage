export type CaptureIntervalValue = number | null | "custom";

export interface CaptureIntervalChoice {
  label: string;
  value: CaptureIntervalValue;
  description: string;
}

export type CollectorSetupAction = "home" | "interval" | "transitions" | "transferFolder" | "migration" | "capture";

export interface CollectorSetupChoice {
  label: string;
  description: string;
  detail: string;
  action: CollectorSetupAction;
}

export function collectorSetupChoices(codexHome: string): CollectorSetupChoice[] {
  return [
    {
      label: "$(folder) Choose CODEX_HOME",
      description: codexHome,
      detail: "Select the Codex sessions folder that this VS Code installation should capture.",
      action: "home",
    },
    {
      label: "$(clock) Set capture interval",
      description: "Choose a scheduled interval or Manual only.",
      detail: "The parent-bound collector stops when VS Code closes.",
      action: "interval",
    },
    {
      label: "$(arrow-left-right) Configure project transitions",
      description: "Choose whether capture infers verified repository switches.",
      detail: "This setting is shared with the native app.",
      action: "transitions",
    },
    {
      label: "$(folder) Choose Task Transfer folder",
      description: "Set the shared folder for importing and exporting tasks.",
      detail: "Use a folder synchronized by your preferred file-sync service.",
      action: "transferFolder",
    },
    {
      label: "$(database) Migrate legacy usage cache",
      description: "Preview and import compatible pre-2.0 usage data.",
      detail: "Conflicting histories require an explicit source choice.",
      action: "migration",
    },
    {
      label: "$(play) Capture now",
      description: "Run one immediate ledger capture.",
      detail: "Useful after initial setup or before deleting a task.",
      action: "capture",
    },
  ];
}

export function projectTransitionChoices(current: boolean): Array<{ label: string; enabled: boolean; description: string }> {
  return [
    {
      label: "Enable project transitions",
      enabled: true,
      description: current ? "Current" : "Split usage at verified local repository changes.",
    },
    {
      label: "Disable project transitions",
      enabled: false,
      description: current ? "Keep all usage in its current project grouping." : "Current",
    },
  ];
}

export function captureIntervalChoices(current: number | null): CaptureIntervalChoice[] {
  return [
    {
      label: "Manual only",
      value: null,
      description: current === null ? "Current · Capture runs only when you choose Capture Now." : "Capture runs only when you choose Capture Now.",
    },
    ...[5, 15, 30, 60].map((minutes) => ({
      label: `Every ${minutes} minutes`,
      value: minutes,
      description: current === minutes ? "Current" : "",
    })),
    { label: "Custom interval…", value: "custom" as const, description: "Choose 1 to 1,440 minutes." },
  ];
}

export function validateCaptureInterval(value: string): string | undefined {
  const minutes = Number(value);
  return Number.isInteger(minutes) && minutes >= 1 && minutes <= 1_440
    ? undefined
    : "Enter a whole number from 1 to 1,440.";
}

export function captureScheduleMessage(interval: number | null): string {
  return interval === null
    ? "Codex Usage is set to Manual only. Use Capture Now whenever you want a refresh."
    : `Codex Usage will capture every ${interval} minutes while VS Code is open.`;
}
