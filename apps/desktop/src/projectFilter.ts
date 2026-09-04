import { escapeHtml } from "./format";
import type { AppState } from "./state";
import { refreshIcons } from "./ui";

export function projectFilterLabel(state: AppState): string {
  if (state.selectedProjectKeys.length === 0) return "All projects";
  if (state.selectedProjectKeys.length === 1) {
    return state.projects.find((project) => project.project_key === state.selectedProjectKeys[0])?.project_label ?? "1 project";
  }
  return `${state.selectedProjectKeys.length} projects`;
}

export function openProjectFilter(
  state: AppState,
  onApply: () => void | Promise<void>,
): void {
  const dialog = document.createElement("dialog");
  dialog.className = "dialog project-dialog";
  const selected = new Set(state.selectedProjectKeys);
  dialog.innerHTML = `<form method="dialog"><header><div><p class="eyebrow">Project filter</p><h2>Choose Projects</h2></div><button class="icon-button" value="cancel" aria-label="Close"><i data-lucide="x"></i></button></header><div class="dialog-list"><label class="check-row"><input type="checkbox" data-all${selected.size === 0 ? " checked" : ""}><span><strong>All projects</strong><small>Include every project in the ledger</small></span></label>${state.projects.map((project) => `<label class="check-row"><input type="checkbox" value="${escapeHtml(project.project_key)}"${selected.has(project.project_key) ? " checked" : ""}><span><strong>${escapeHtml(project.project_label)}</strong><small>${project.task_count.toLocaleString()} tasks</small></span></label>`).join("")}</div><footer><button class="button-quiet" value="cancel">Cancel</button><button class="button-primary" value="apply">Apply</button></footer></form>`;
  const all = dialog.querySelector<HTMLInputElement>("[data-all]")!;
  const projectChecks = [...dialog.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:not([data-all])')];
  all.addEventListener("change", () => {
    if (all.checked) projectChecks.forEach((input) => { input.checked = false; });
  });
  projectChecks.forEach((input) => input.addEventListener("change", () => {
    if (input.checked) all.checked = false;
    if (!projectChecks.some((candidate) => candidate.checked)) all.checked = true;
  }));
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue === "apply") {
      state.selectedProjectKeys = all.checked ? [] : projectChecks.filter((input) => input.checked).map((input) => input.value);
      await onApply();
    }
    dialog.remove();
  });
  document.body.append(dialog);
  refreshIcons(dialog);
  dialog.showModal();
}
