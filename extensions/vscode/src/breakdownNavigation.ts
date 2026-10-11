import type { BreakdownAction, BreakdownNavigation } from "./types";

const STATE_KEYS = "basis,day,detail,grain,group,metric,overlay,project,view";

export function validateBreakdownNavigation(value: unknown, current: BreakdownNavigation | undefined): BreakdownAction | undefined {
  if (!current || !value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const args = value as Record<string, unknown>;
  if (Object.keys(args).sort().join(",") !== "scope,state" || args.scope !== current.scope || !/^[a-f0-9]{64}$/u.test(current.scope)) return undefined;
  if (!args.state || typeof args.state !== "object" || Array.isArray(args.state)) return undefined;
  const state = args.state as Record<string, unknown>;
  if (Object.keys(state).sort().join(",") !== STATE_KEYS || Object.values(state).some(v => typeof v !== "string")) return undefined;
  if (state.basis !== "selected" || !["time", "project"].includes(state.view as string) ||
      !["daily", "hourly"].includes(state.grain as string) || !["weekly", "balance", "none"].includes(state.overlay as string) ||
      !["tokens", "cost", "credits"].includes(state.metric as string) || !["model", "project"].includes(state.group as string)) return undefined;
  return current.actions.find(action => action.scope === args.scope && Object.keys(action.state).every(key => action.state[key as keyof typeof action.state] === state[key]));
}
