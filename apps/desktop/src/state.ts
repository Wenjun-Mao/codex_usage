import type { AgentSettings, AgentStatus, ProjectSummary, ViewName } from "./types";

export interface CustomDateRange {
  startDate: string;
  endDate: string;
}

export interface AppState {
  settings: AgentSettings;
  status: AgentStatus;
  projects: ProjectSummary[];
  selectedProjectKeys: string[];
  range: string;
  customRange: CustomDateRange | null;
  view: ViewName;
}

export type RefreshStatus = () => Promise<void>;
export type Navigate = (view: ViewName) => Promise<void>;
