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
      capabilities: ["custom-report-range", "agent-activity", "image-reporting"],
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
    customRange: null,
    view: "usage",
  };
}

beforeEach(() => {
  resetTransferSelection();
  localStorage.clear();
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
    expect(root.querySelector("#storage-refresh")?.getAttribute("aria-label")).toBe(
      "Reload storage inventory",
    );
    expect(root.querySelector("#storage-project-filter")?.textContent).toContain(
      "All projects",
    );
  });

  test("Usage renders the report returned by the ledger and load diagnostics", async () => {
    const root = document.querySelector<HTMLElement>("#root")!;
    await renderUsageView(root, appState());

    const frame = root.querySelector<HTMLIFrameElement>("#usage-report")!;
    expect(frame.srcdoc).toContain("Project Breakdown");
    expect(frame.srcdoc).toContain("Cost Trend");
    expect(frame.srcdoc).toContain('id="cost-trend-week"');
    expect(frame.srcdoc).toContain('id="cost-trend-month"');
    expect(frame.srcdoc).toContain("Compare by");
    expect(frame.srcdoc).toContain("API cost");
    expect(frame.srcdoc).toContain('id="compare-scale-cost"');
    expect(frame.srcdoc).toContain("--cost-width:");
    const modelMix = frame.srcdoc.slice(frame.srcdoc.indexOf("<h2>Model Mix</h2>"));
    expect(modelMix.indexOf("gpt-6-astra")).toBeLessThan(
      modelMix.indexOf("gpt-5.6-sol"),
    );
    expect(frame.srcdoc).toContain('data-codex-host="native"');
    expect(root.querySelector("#report-diagnostics")?.textContent).toContain(
      "Ledger revision 82",
    );
    expect(root.querySelector("#usage-reload")?.getAttribute("aria-label")).toBe(
      "Reload usage from ledger",
    );
    expect(root.textContent).toContain(
      "Captured token usage for the selected range and projects.",
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

  test("Usage keeps a custom calendar range per native client and cancellation preserves the report", async () => {
    const root = document.querySelector<HTMLElement>("#root")!;
    const state = appState();
    await renderUsageView(root, state);
    const dialog = root.querySelector<HTMLDialogElement>("#custom-range-dialog")!;
    Object.defineProperty(dialog, "showModal", { value: () => dialog.setAttribute("open", ""), configurable: true });
    Object.defineProperty(dialog, "close", { value: () => dialog.removeAttribute("open"), configurable: true });
    const range = root.querySelector<HTMLSelectElement>("#usage-range")!;
    range.value = "custom";
    range.dispatchEvent(new Event("change", { bubbles: true }));
    expect(dialog.open).toBe(true);
    root.querySelector<HTMLButtonElement>("#custom-range-cancel")!.click();
    expect(state.range).toBe("30d");

    range.value = "custom";
    range.dispatchEvent(new Event("change", { bubbles: true }));
    root.querySelector<HTMLInputElement>("#custom-range-start")!.value = "2026-08-27";
    root.querySelector<HTMLInputElement>("#custom-range-end")!.value = "2026-09-02";
    root.querySelector<HTMLFormElement>("#custom-range-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(state.range).toBe("custom");
    expect(state.customRange).toEqual({ startDate: "2026-08-27", endDate: "2026-09-02" });
    expect(JSON.parse(localStorage.getItem("codex-usage-custom-report-range") || "null")).toEqual(state.customRange);
  });

  test("Usage surfaces capability mismatch instead of issuing unsupported custom or export requests", async () => {
    const root = document.querySelector<HTMLElement>("#root")!;
    const state = appState();
    state.status.capabilities = [];
    await renderUsageView(root, state);
    const range = root.querySelector<HTMLSelectElement>("#usage-range")!;
    range.value = "custom";
    range.dispatchEvent(new Event("change", { bubbles: true }));
    expect(state.range).toBe("30d");
    root.querySelector<HTMLButtonElement>("#export-agent-activity")!.click();
    expect(document.querySelector("#toast-region")?.textContent).toContain("out of date");
  });
});
