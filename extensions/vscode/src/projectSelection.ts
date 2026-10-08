import type { ProjectSummary } from "./types";

export interface ProjectChoice {
  label: string;
  description: string;
  key: string;
  picked: boolean;
}

export async function chooseProjects(
  projects: ProjectSummary[], current: string[],
  chooseMode: () => Promise<"all" | "subset" | undefined>,
  chooseSubset: (choices: ProjectChoice[]) => Promise<ProjectChoice[] | undefined>,
): Promise<string[] | undefined> {
  const mode = await chooseMode();
  if (!mode) return undefined;
  if (mode === "all") return [];
  const selected = new Set(current);
  const choices = projects.map((project) => ({
    label: project.project_label,
    description: `${project.task_count.toLocaleString()} tasks - ${project.project_key}`,
    key: project.project_key,
    picked: selected.has(project.project_key),
  }));
  const picked = await chooseSubset(choices);
  return picked === undefined ? undefined : [...new Set(picked.map((item) => item.key))];
}
