import { chartQuery, validateSpeedNavigation, type SpeedChartState } from "./speedNavigation";
import { validateBreakdownNavigation } from "./breakdownNavigation";
import { validateAllowanceHistory } from "./allowanceHistoryNavigation";
import type { AllowanceHistoryAction, AllowanceHistoryNavigation } from "./types";
import type { AgentStatus, BreakdownAction, BreakdownNavigation, RenderedReport, SpeedNavigation } from "./types";
import { AgentRequestError } from "./agentClient";

/** Own transient chart state without persisting commands across evidence revisions. */
export class DashboardNavigation {
  private identity?: string;
  private revision?: number;
  private speedNavigation?: SpeedNavigation;
  private speedState?: SpeedChartState;
  private breakdownNavigation?: BreakdownNavigation;
  private breakdownAction?: BreakdownAction;
  private issuedEvidence?: string;
  private queryEvidence?: string;
  private allowanceNavigation?: AllowanceHistoryNavigation;
  private allowanceAction?: AllowanceHistoryAction;

  reset(): void {
    this.allowanceAction = undefined;
    this.allowanceNavigation = undefined;
    this.breakdownAction = undefined;
    this.breakdownNavigation = undefined;
    this.speedState = undefined;
    this.speedNavigation = undefined;
  }

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

  allowance(value: unknown): boolean {
    const action = validateAllowanceHistory(value, this.allowanceNavigation);
    if (!action) return false;
    this.allowanceAction = action;
    return true;
  }

  query(query: URLSearchParams, identity: string, status: AgentStatus): void {
    if (identity !== this.identity) {
      this.allowanceAction = undefined;
      this.allowanceNavigation = undefined;
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
    this.queryEvidence = JSON.stringify([status.plan_allowance?.probe_status, !!weeklyExpired]);
    if (this.revision === undefined || status.ledger_revision > this.revision ||
        (status.ledger_revision === this.revision && (this.breakdownAction || this.allowanceAction) &&
          this.queryEvidence !== this.issuedEvidence)) {
      this.breakdownAction = undefined;
      this.breakdownNavigation = undefined;
      this.allowanceAction = undefined;
      this.allowanceNavigation = undefined;
    }
    chartQuery(query, this.speedState, this.speedNavigation?.scope);
    if (this.breakdownAction) query.set("breakdown_action", JSON.stringify(this.breakdownAction));
    if (this.allowanceAction) query.set("allowance_action", JSON.stringify(this.allowanceAction));
  }

  async report(client: { get<T>(path: string): Promise<T> }, query: URLSearchParams): Promise<RenderedReport> {
    try {
      return await client.get<RenderedReport>(`/v1/report?${query}`);
    } catch (error) {
      if (!(error instanceof AgentRequestError) || error.status !== 409 || !(
        (error.code === "breakdown_scope_expired" && query.has("breakdown_action")) ||
        (error.code === "allowance_scope_expired" && query.has("allowance_action")))) throw error;
      // Only a server-confirmed previously issued scope can recover. Calendar,
      // timezone and transition settings are resolved by the owning backend.
      this.reset();
      const fresh = new URLSearchParams(query);
      for (const key of ["allowance_action", "breakdown_action", "speed_granularity", "speed_window_start", "speed_window_scope"]) fresh.delete(key);
      return client.get<RenderedReport>(`/v1/report?${fresh}`);
    }
  }

  accept(report: RenderedReport): void {
    this.revision = report.ledger_revision;
    this.speedNavigation = report.speed_navigation;
    if (this.speedState && this.speedNavigation) this.speedState.windowStart = this.speedNavigation.window_start;
    this.breakdownNavigation = report.breakdown_navigation;
    this.allowanceNavigation = report.allowance_navigation;
    this.allowanceAction = this.allowanceNavigation?.actions.find(action =>
      Object.entries(action.state).every(([key, value]) => value === this.allowanceNavigation?.state[key as keyof typeof action.state]));
    const evidence = this.breakdownNavigation?.evidence_state;
    this.issuedEvidence = evidence ? JSON.stringify([evidence.probe_status, evidence.deadline_elapsed]) : this.queryEvidence;
    this.breakdownAction = this.breakdownNavigation?.actions.find(action =>
      Object.entries(action.state).every(([key, value]) => value === this.breakdownNavigation?.state[key as keyof typeof action.state]));
  }
}
