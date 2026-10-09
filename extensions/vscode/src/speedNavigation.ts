import type { SpeedNavigation } from "./types";

export interface SpeedChartState {
  granularity: "daily" | "hourly";
  windowStart: string;
}

function calendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function validateSpeedNavigation(value: unknown, current: SpeedNavigation | undefined): SpeedChartState | undefined {
  if (!current || !value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const args = value as Record<string, unknown>;
  if (Object.keys(args).sort().join(",") !== "granularity,scope,windowStart") return undefined;
  if (args.scope !== current.scope || !/^[a-f0-9]{64}$/u.test(current.scope)) return undefined;
  if (args.granularity !== "daily" && args.granularity !== "hourly") return undefined;
  if (!calendarDate(args.windowStart) || args.windowStart < current.min_date || args.windowStart > current.max_date) return undefined;
  if (!calendarDate(current.min_date) || !calendarDate(current.max_date)) return undefined;
  const latest = new Date(`${current.max_date}T00:00:00Z`);
  latest.setUTCDate(latest.getUTCDate() - 6);
  const latestStart = latest.toISOString().slice(0, 10) < current.min_date ? current.min_date : latest.toISOString().slice(0, 10);
  if (args.windowStart !== current.window_start && args.windowStart !== current.previous && args.windowStart !== current.next && args.windowStart !== latestStart) return undefined;
  return { granularity: args.granularity, windowStart: args.windowStart };
}

export function chartQuery(query: URLSearchParams, state: SpeedChartState | undefined, scope: string | undefined): URLSearchParams {
  if (state && scope) {
    query.set("speed_granularity", state.granularity);
    query.set("speed_window_start", state.windowStart);
    query.set("speed_window_scope", scope);
  }
  return query;
}
