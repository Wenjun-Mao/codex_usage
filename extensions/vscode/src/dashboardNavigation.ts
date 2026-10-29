import { chartQuery, validateSpeedNavigation, type SpeedChartState } from "./speedNavigation";
import { validateBreakdownNavigation } from "./breakdownNavigation";
import { AllowanceHistoryIntent } from "./allowanceHistoryNavigation";
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
  private readonly history = new AllowanceHistoryIntent();

  reset(forgetHistory = false): void {
    this.history.reset(forgetHistory);
    this.resetCharts();
  }

  private resetCharts(): void {
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
    return this.history.select(value);
  }

  query(query: URLSearchParams, identity: string, status: AgentStatus): void {
    if (identity !== this.identity) {
      this.history.contextChanged();
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
        (status.ledger_revision === this.revision &&
          this.queryEvidence !== this.issuedEvidence)) {
      this.breakdownAction = undefined;
      this.breakdownNavigation = undefined;
      this.history.reset();
    }
    chartQuery(query, this.speedState, this.speedNavigation?.scope);
    if (this.breakdownAction) query.set("breakdown_action", JSON.stringify(this.breakdownAction));
    this.history.query(query);
  }

  async report(client: { get<T>(path: string): Promise<T> }, query: URLSearchParams): Promise<RenderedReport> {
    const fresh = new URLSearchParams(query);
    const recovered = new Set<string>();
    while (true) {
      try {
        const report = await client.get<RenderedReport>(`/v1/report?${fresh}`);
        this.verifyHistoryMode(report, fresh);
        return report;
      } catch (error) {
        if (!(error instanceof AgentRequestError) || error.status !== 409 || !error.code || recovered.has(error.code) || !(
          (error.code === "breakdown_scope_expired" && fresh.has("breakdown_action")) ||
          (error.code === "allowance_scope_expired" && fresh.has("allowance_action")))) throw error;
        // Each server-confirmed issued domain can expire once. A calendar-only
        // chart expiry must not discard a still-valid account history selection.
        recovered.add(error.code);
        if (error.code === "allowance_scope_expired") {
          this.reset();
          fresh.delete("allowance_action");
        } else this.resetCharts();
        for (const key of ["breakdown_action", "speed_granularity", "speed_window_start", "speed_window_scope"]) fresh.delete(key);
      }
    }
  }

  accept(report: RenderedReport): void {
    this.revision = report.ledger_revision;
    this.speedNavigation = report.speed_navigation;
    if (this.speedState && this.speedNavigation) this.speedState.windowStart = this.speedNavigation.window_start;
    this.breakdownNavigation = report.breakdown_navigation;
    this.history.accept(report.allowance_navigation);
    const evidence = this.breakdownNavigation?.evidence_state;
    this.issuedEvidence = evidence ? JSON.stringify([evidence.probe_status, evidence.deadline_elapsed]) : this.queryEvidence;
    this.breakdownAction = this.breakdownNavigation?.actions.find(action =>
      Object.entries(action.state).every(([key, value]) => value === this.breakdownNavigation?.state[key as keyof typeof action.state]));
  }

  private verifyHistoryMode(report: RenderedReport, query: URLSearchParams): void {
    const mode = query.get("allowance_history");
    if (mode && (!report.allowance_navigation ||
        (mode === "deferred" && !query.has("allowance_action")) !== (report.allowance_navigation.deferred === true))) {
      throw new Error("The collector did not return the requested allowance history mode; reinstall the matching VSIX package.");
    }
  }
}
