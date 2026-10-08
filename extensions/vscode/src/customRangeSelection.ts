import * as vscode from "vscode";
import type { CustomDateRange } from "./types";

export async function selectCustomRange(selected?: CustomDateRange): Promise<CustomDateRange | undefined> {
  const current = selected || latestSevenDays();
  const today = localCalendarDate(new Date());
  const startDate = await vscode.window.showInputBox({
    title: "Custom usage range: start date",
    prompt: "Enter an inclusive local calendar date (YYYY-MM-DD).",
    value: current.startDate,
    validateInput: (value) => validateCalendarDate(value, today),
  });
  if (startDate === undefined) return undefined;
  const endDate = await vscode.window.showInputBox({
    title: "Custom usage range: end date",
    prompt: "Enter an inclusive local calendar date (YYYY-MM-DD).",
    value: current.endDate,
    validateInput: (value) => {
      const validation = validateCalendarDate(value, today);
      return validation || (value < startDate ? "End date must be on or after the start date." : undefined);
    },
  });
  if (endDate === undefined) return undefined;
  return { startDate, endDate };
}

function latestSevenDays(): CustomDateRange {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  return { startDate: localCalendarDate(start), endDate: localCalendarDate(end) };
}

function localCalendarDate(value: Date): string {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function validateCalendarDate(value: string, today: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    return "Enter a valid YYYY-MM-DD calendar date.";
  }
  return value > today ? "Custom ranges cannot include future dates." : undefined;
}
