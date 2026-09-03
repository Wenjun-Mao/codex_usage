import type { AgentSettings, AgentStatus, ProjectSummary, ViewName } from "./types";

export interface AppState {
  settings: AgentSettings;
  status: AgentStatus;
  projects: ProjectSummary[];
  selectedProjectKeys: string[];
  range: string;
  view: ViewName;
}

export type RefreshStatus = () => Promise<void>;
export type Navigate = (view: ViewName) => Promise<void>;
