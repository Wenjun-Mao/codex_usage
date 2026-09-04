import { beforeEach, describe, expect, test } from "vitest";
import { renderOnboarding } from "./onboarding";
import type { AppState } from "./state";
import { renderStorageView } from "./storageView";
import { renderTransferView, resetTransferSelection } from "./transferView";
import { renderUsageView } from "./usageView";
import { usageReportNeedsRefresh, usageStatusFingerprint } from "./usageRefreshPolicy";

function appState(): AppState {
  return {
    settings: {
      schema_version: 1,
      codex_home: "/Users/demo/.codex",
      capture_interval_minutes: 15,
      background_capture: true,
      daily_update_checks: false,
      onboarding_complete: true,
      native_onboarding_complete: true,
      timezone: "UTC",
      theme: "night",
      auto_project_transitions: true,
      transfer_folder: "/Users/demo/OneDrive/Codex",
    },
    status: {
      agent_pid: 10,
      api_version: 1,
      codex_home: "/Users/demo/.codex",
      capture_running: false,
      next_capture_seconds: 900,
      dirty_paths: 0,
      ledger_revision: 82,
      last_capture_at: "2026-09-02T12:00:00Z",
      last_capture_outcome: "success",
      last_capture_error: "",
      coverage: {
        complete: true,
        fraction: 1,
        total_sources: 3,
        captured_sources: 3,
        stale_sources: 0,
        pending_files: 0,
        pending_bytes: 0,
        total_bytes: 100,
        captured_bytes: 100,
      },
    },
    projects: [],
    selectedProjectKeys: [],
    range: "30d",
    view: "usage",
  };
}

beforeEach(() => {
  resetTransferSelection();
  document.body.innerHTML = '<div id="toast-region"></div><main id="root"></main>';
});

describe("native views", () => {
  test("first-run background capture requires explicit consent", () => {
    const container = document.createElement("div");
    container.innerHTML = renderOnboarding(appState().settings);

    expect(container.querySelector<HTMLInputElement>("#onboarding-background")?.checked).toBe(false);
    expect(container.querySelector<HTMLInputElement>("#onboarding-updates")?.checked).toBe(false);
  });

  test("Task Transfer selects one project, then starts with no tasks selected", async () => {
    const root = document.querySelector<HTMLElement>("#root")!;
    await renderTransferView(root, appState());

    const projects = root.querySelectorAll<HTMLButtonElement>(".project-row");
    expect(projects.length).toBeGreaterThan(1);
    projects[0]!.click();

    expect(root.textContent).toContain("Step 2 of 2");
    expect(root.textContent).toContain("Nothing is selected by default");
    expect(root.querySelectorAll<HTMLInputElement>("[data-task-id]:checked")).toHaveLength(0);
    expect(root.querySelector<HTMLElement>("#selected-task-count")?.textContent).toBe("0");
    expect(root.querySelector<HTMLButtonElement>("#execute-transfer")?.disabled).toBe(true);

    const task = root.querySelector<HTMLInputElement>("[data-task-id]")!;
    task.checked = true;
    task.dispatchEvent(new Event("change", { bubbles: true }));
    expect(root.querySelector<HTMLElement>("#selected-task-count")?.textContent).toBe("1");

    root.querySelector<HTMLButtonElement>("#transfer-back")!.click();
    expect(root.textContent).toContain("Step 1 of 2");
    expect(root.textContent).toContain("Choose One Project");
  });

  test("Task Storage is read-only apart from explicit Analyze actions", async () => {
    const root = document.querySelector<HTMLElement>("#root")!;
    await renderStorageView(root, appState());

    expect(root.querySelectorAll(".analyze-button").length).toBeGreaterThan(0);
    expect(root.textContent).not.toContain("Back Up");
    expect(root.textContent).not.toContain("Rollover");
    expect(root.textContent).toContain("Largest Task Trees");
  });

  test("Usage renders the report returned by the ledger and load diagnostics", async () => {
    const root = document.querySelector<HTMLElement>("#root")!;
    await renderUsageView(root, appState());

    const frame = root.querySelector<HTMLIFrameElement>("#usage-report")!;
    expect(frame.srcdoc).toContain("Project Breakdown");
    expect(root.querySelector("#report-diagnostics")?.textContent).toContain(
      "Ledger revision 82",
    );
    expect(JSON.parse(root.dataset.usageStatusFingerprint ?? "[]")[0]).toBe(82);
  });

  test("Usage refresh policy notices baseline progress without reacting to timers", () => {
    const rendered = appState().status;
    const fingerprint = usageStatusFingerprint(rendered);

    expect(usageReportNeedsRefresh(fingerprint, rendered)).toBe(false);
    expect(usageReportNeedsRefresh(fingerprint, {
      ...rendered,
      next_capture_seconds: 885,
    })).toBe(false);
    expect(usageReportNeedsRefresh(fingerprint, {
      ...rendered,
      ledger_revision: 83,
      coverage: {
        ...rendered.coverage,
        complete: false,
        fraction: 0.75,
        pending_files: 1,
        pending_bytes: 25,
      },
    })).toBe(true);
  });
});
