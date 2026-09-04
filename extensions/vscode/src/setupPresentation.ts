export type CaptureIntervalValue = number | null | "custom";

export interface CaptureIntervalChoice {
  label: string;
  value: CaptureIntervalValue;
  description: string;
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
