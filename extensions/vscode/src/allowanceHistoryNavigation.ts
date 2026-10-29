import type { AllowanceHistoryAction, AllowanceHistoryNavigation } from "./types";

const KEYS = "capture_order,capture_page,fit_page,index,kind,period_page,uncertain_page";

export function validateAllowanceHistory(value: unknown, current: AllowanceHistoryNavigation | undefined): AllowanceHistoryAction | undefined {
  if (!current || !value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const args = value as Record<string, unknown>;
  if (Object.keys(args).sort().join(",") !== "scope,state" || args.scope !== current.scope || !/^[a-f0-9]{64}$/u.test(current.scope)) return undefined;
  if (!args.state || typeof args.state !== "object" || Array.isArray(args.state)) return undefined;
  const state = args.state as Record<string, unknown>;
  if (Object.keys(state).sort().join(",") !== KEYS || !["", "periods", "uncertain", "cross"].includes(state.kind as string) ||
      !["newest", "oldest"].includes(state.capture_order as string)) return undefined;
  for (const key of ["period_page", "uncertain_page", "fit_page", "capture_page", "index"]) {
    if (!Number.isSafeInteger(state[key]) || (state[key] as number) < (key === "index" ? -1 : 0) || (state[key] as number) > 2**31-1) return undefined;
  }
  if (["", "cross"].includes(state.kind as string) ? state.index !== -1 : (state.index as number) < 0) return undefined;
  return current.actions.find(action => action.scope === args.scope &&
    Object.entries(action.state).every(([key, field]) => field === state[key]));
}

/** A displayed invitation is not user intent. Intent lasts only for this panel. */
export class AllowanceHistoryIntent {
  private navigation?: AllowanceHistoryNavigation;
  private action?: AllowanceHistoryAction;
  private requested = false;

  reset(forgetIntent = false): void {
    this.navigation = undefined;
    this.action = undefined;
    if (forgetIntent) this.requested = false;
  }

  contextChanged(): void {
    if (!this.requested) this.reset();
  }

  select(value: unknown): boolean {
    const action = validateAllowanceHistory(value, this.navigation);
    if (!action) return false;
    this.requested = true;
    this.action = action;
    return true;
  }

  query(query: URLSearchParams): void {
    query.set("allowance_history", this.requested ? "requested" : "deferred");
    if (this.action) query.set("allowance_action", JSON.stringify(this.action));
  }

  accept(navigation: AllowanceHistoryNavigation | undefined): void {
    this.navigation = navigation;
    // Only explicit selection sets requested; an advertised load stays inert.
    this.action = this.requested && !navigation?.deferred ? navigation?.actions.find(action =>
      Object.entries(action.state).every(([key, value]) => value === navigation.state[key as keyof typeof action.state])) : undefined;
  }
}
