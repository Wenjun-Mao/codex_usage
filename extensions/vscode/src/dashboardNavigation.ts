import { chartQuery, validateSpeedNavigation, type SpeedChartState } from "./speedNavigation";
import { validateBreakdownNavigation } from "./breakdownNavigation";
import type { AgentStatus, BreakdownAction, BreakdownNavigation, RenderedReport, SpeedNavigation } from "./types";

/** Own transient chart state without persisting commands across evidence revisions. */
export class DashboardNavigation {
  private identity?: string;
  private revision?: number;
  private speedNavigation?: SpeedNavigation;
  private speedState?: SpeedChartState;
  private breakdownNavigation?: BreakdownNavigation;
  private breakdownAction?: BreakdownAction;

  speed(value: unknown): boolean {
    const state = validateSpeedNavigation(value, this.speedNavigation);
    if (!state) return false;
    this.speedState = state;
    return true;
  }

  breakdown(value: unknown): boolean {
    const action = validateBreakdownNavigation(value, this.breakdownNavigation);
    if (!action) return false;
    this.breakdownAction = action;
    return true;
  }

  query(query: URLSearchParams, identity: string, status: AgentStatus): void {
    if (identity !== this.identity) {
      this.speedState = undefined;
      this.speedNavigation = undefined;
      this.breakdownAction = undefined;
      this.breakdownNavigation = undefined;
      this.identity = identity;
    }
    // A cached status can precede a report prepared during startup capture.
    // Only equally new evidence can invalidate the rendered command scope.
    const weeklyExpired = status.plan_allowance?.active_buckets.some(bucket =>
      bucket.duration_minutes === 10080 && bucket.resets_at !== null && bucket.resets_at <= Date.now() / 1000);
    if (this.revision === undefined || status.ledger_revision > this.revision ||
        (status.ledger_revision === this.revision && this.breakdownAction?.state.basis === "cycle" &&
          (status.plan_allowance?.probe_status !== "fresh" || weeklyExpired))) {
      this.breakdownAction = undefined;
      this.breakdownNavigation = undefined;
    }
    chartQuery(query, this.speedState, this.speedNavigation?.scope);
    if (this.breakdownAction) query.set("breakdown_action", JSON.stringify(this.breakdownAction));
  }

  accept(report: RenderedReport): void {
    this.revision = report.ledger_revision;
    this.speedNavigation = report.speed_navigation;
    if (this.speedState && this.speedNavigation) this.speedState.windowStart = this.speedNavigation.window_start;
    this.breakdownNavigation = report.breakdown_navigation;
    this.breakdownAction = this.breakdownNavigation?.actions.find(action =>
      Object.entries(action.state).every(([key, value]) => value === this.breakdownNavigation?.state[key as keyof typeof action.state]));
  }
}
