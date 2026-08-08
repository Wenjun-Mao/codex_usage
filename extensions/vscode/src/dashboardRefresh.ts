import * as fs from "fs/promises";
import * as path from "path";
import { performance } from "perf_hooks";

import {
  buildCodexUsageEnv,
  buildReportArgs,
  cacheDbPath,
  legacyCacheDbPaths,
  type ExtensionSettings,
  type ReportView,
} from "./core";
import {
  injectWebviewControls,
  injectWebviewCsp,
  renderErrorHtml,
  renderLoadingHtml,
} from "./dashboardWebview";
import {
  LatestRefreshCoordinator,
  type RefreshPublication,
} from "./latestRefreshCoordinator";

export type DashboardLoadingKind = "initializing" | "rebuilding" | "refreshing";

export type DashboardPanel = {
  webview: {
    html: string;
    cspSource: string;
  };
};

export type DashboardRefreshRequest = {
  requestId: number;
  panel: DashboardPanel;
  settings: ExtensionSettings;
  versionLabel: string;
  reportViewState: DashboardReportViewState;
  reportPath: string;
  timingOutputPath: string;
};

export type DashboardReportViewState = {
  current: ReportView;
};

export type DashboardTimingDiagnostics = {
  phaseSeconds: Record<string, number>;
  cliSeconds: number | undefined;
  cache: DashboardCacheDiagnostics | undefined;
};

export type DashboardCacheDiagnostics = {
  rebuilt: boolean;
  filesTotal: number;
  filesParsed: number;
  filesFullParsed: number;
  filesAppended: number;
  appendFallbacks: number;
  sourceBytesRead: number;
  filesReused: number;
};

export type DashboardStatusIntent = {
  loadingKind: DashboardLoadingKind;
};

export type DashboardRefreshResult =
  | {
    kind: "success";
    html: string;
    settings: ExtensionSettings;
    elapsedSeconds: number;
    timing: DashboardTimingDiagnostics | undefined;
    warnings: string[];
    status: DashboardStatusIntent;
  }
  | {
    kind: "error";
    settings: ExtensionSettings;
    message: string;
    warnings: string[];
    status: DashboardStatusIntent;
  };

type RunCodexUsage = (
  executablePath: string,
  args: string[],
  env: NodeJS.ProcessEnv,
) => Promise<{ stdout: string; stderr: string }>;

export type DashboardExecutionDependencies = {
  globalStoragePath: string;
  resolveExecutable: () => Promise<string>;
  runCodexUsage: RunCodexUsage;
};

export type DashboardRefreshDependencies = DashboardExecutionDependencies & {
  appendOutput: (line: string) => void;
  updateStatus: (intent: DashboardStatusIntent) => void;
  showError: (message: string) => PromiseLike<unknown> | void;
};

export function createDashboardRefreshRequest(options: {
  requestId: number;
  panel: DashboardPanel;
  settings: ExtensionSettings;
  versionLabel: string;
  reportViewState: DashboardReportViewState;
  globalStoragePath: string;
}): DashboardRefreshRequest {
  const artifactPrefix = `dashboard-${options.requestId}`;
  return {
    requestId: options.requestId,
    panel: options.panel,
    settings: options.settings,
    versionLabel: options.versionLabel,
    reportViewState: options.reportViewState,
    reportPath: path.join(options.globalStoragePath, `${artifactPrefix}.html`),
    timingOutputPath: path.join(options.globalStoragePath, `${artifactPrefix}.timing.json`),
  };
}

export function createDashboardRefreshCoordinator(
  dependencies: DashboardRefreshDependencies,
): LatestRefreshCoordinator<DashboardRefreshRequest, DashboardRefreshResult> {
  return new LatestRefreshCoordinator(
    (request) => executeDashboardRefresh(request, dependencies),
    (request, result, publication) =>
      publishDashboardRefresh(request, result, dependencies, publication),
  );
}

export async function dashboardLoadingKind(globalStoragePath: string): Promise<DashboardLoadingKind> {
  if (await pathExists(cacheDbPath(globalStoragePath))) {
    return "refreshing";
  }
  for (const legacyPath of legacyCacheDbPaths(globalStoragePath)) {
    if (await pathExists(legacyPath)) {
      return "rebuilding";
    }
  }
  return "initializing";
}

export async function executeDashboardRefresh(
  request: DashboardRefreshRequest,
  dependencies: DashboardExecutionDependencies,
): Promise<DashboardRefreshResult> {
  const loadingKind = await dashboardLoadingKind(dependencies.globalStoragePath);
  setDashboardLoading(request, loadingKind);
  const startedAt = performance.now();
  const status = { loadingKind };

  try {
    await fs.mkdir(dependencies.globalStoragePath, { recursive: true });
    const executablePath = await dependencies.resolveExecutable();
    await dependencies.runCodexUsage(
      executablePath,
      buildReportArgs({
        range: request.settings.range,
        outputPath: request.reportPath,
        timingOutputPath: request.timingOutputPath,
        projectKeys: request.settings.projectKeys,
        theme: request.settings.theme,
        projectTransitions: request.settings.projectTransitions,
      }),
      buildCodexUsageEnv(dependencies.globalStoragePath),
    );
    const html = await fs.readFile(request.reportPath, "utf8");
    const timingResult = await readTimingDiagnostics(request.timingOutputPath);
    return {
      kind: "success",
      html,
      settings: request.settings,
      elapsedSeconds: (performance.now() - startedAt) / 1000,
      timing: timingResult.timing,
      warnings: [timingResult.warning].filter((warning): warning is string => Boolean(warning)),
      status,
    };
  } catch (error) {
    return {
      kind: "error",
      settings: request.settings,
      message: errorMessage(error),
      warnings: [],
      status,
    };
  }
}

export function publishDashboardRefresh(
  request: DashboardRefreshRequest,
  result: DashboardRefreshResult,
  dependencies: Pick<DashboardRefreshDependencies, "appendOutput" | "updateStatus" | "showError">,
  publication: RefreshPublication,
): void {
  if (result.kind === "success") {
    publication.commit(() => {
      request.panel.webview.html = renderDashboardHtml(
        request,
        result.html,
        result.elapsedSeconds,
      );
    });
    logDiagnostics(dependencies.appendOutput, result, publication);
  } else {
    publication.commit(() => dependencies.appendOutput(`[error] ${result.message}`));
    publication.commit(() => {
      request.panel.webview.html = renderDashboardHtml(
        request,
        renderErrorHtml(`${result.message}\n\nCheck the Codex Usage output channel for details.`),
      );
    });
    logWarnings(dependencies.appendOutput, result.warnings, publication);
    publication.commit(() => {
      void dependencies.showError(`Codex Usage failed: ${result.message}`);
    });
  }
  publication.commit(() => dependencies.updateStatus(result.status));
}

async function readTimingDiagnostics(
  timingOutputPath: string,
): Promise<{ timing: DashboardTimingDiagnostics | undefined; warning: string | undefined }> {
  try {
    const payload = JSON.parse(await fs.readFile(timingOutputPath, "utf8"));
    if (!isRecord(payload) || !isRecord(payload.phases_seconds)) {
      throw new Error("timing sidecar did not contain phases_seconds");
    }
    const phaseSeconds: Record<string, number> = {};
    for (const [phase, seconds] of Object.entries(payload.phases_seconds)) {
      if (typeof seconds === "number" && Number.isFinite(seconds)) {
        phaseSeconds[phase] = seconds;
      }
    }
    const cliSeconds = typeof payload.total_seconds === "number" && Number.isFinite(payload.total_seconds)
      ? payload.total_seconds
      : undefined;
    return {
      timing: {
        phaseSeconds,
        cliSeconds,
        cache: parseCacheDiagnostics(payload.cache),
      },
      warning: undefined,
    };
  } catch (error) {
    return {
      timing: undefined,
      warning: `[timing] timing sidecar unavailable (${timingOutputPath}): ${errorMessage(error)}`,
    };
  }
}

function setDashboardLoading(request: DashboardRefreshRequest, kind: DashboardLoadingKind): void {
  request.panel.webview.html = renderDashboardHtml(request, renderLoadingHtml(loadingMessageFor(kind)));
}

function renderDashboardHtml(
  request: DashboardRefreshRequest,
  rawHtml: string,
  loadedSeconds?: number,
): string {
  return injectWebviewCsp(injectWebviewControls(rawHtml, {
    range: request.settings.range,
    projectKeys: request.settings.projectKeys,
    theme: request.settings.theme,
    taskTransfer: request.settings.taskTransfer,
    reportView: request.reportViewState.current,
    loadedSeconds,
    versionLabel: request.versionLabel,
  }), request.panel.webview.cspSource);
}

function loadingMessageFor(kind: DashboardLoadingKind): string {
  if (kind === "initializing") {
    return "Initializing Codex usage cache. This can take a few seconds the first time.";
  }
  if (kind === "rebuilding") {
    return "Rebuilding usage cache after upgrade...";
  }
  return "Refreshing Codex usage...";
}

function logDiagnostics(
  appendOutput: (line: string) => void,
  result: Extract<DashboardRefreshResult, { kind: "success" }>,
  publication: RefreshPublication,
): void {
  logWarnings(appendOutput, result.warnings, publication);
  const timing = result.timing;
  if (timing) {
    for (const [phase, seconds] of Object.entries(timing.phaseSeconds)) {
      publication.commit(() => appendOutput(`[timing] ${phase}: ${seconds.toFixed(3)}s`));
    }
    const cliSeconds = timing.cliSeconds;
    if (cliSeconds !== undefined && !("total_cli" in timing.phaseSeconds)) {
      publication.commit(() => appendOutput(`[timing] total_cli: ${cliSeconds.toFixed(3)}s`));
    }
    const cache = timing.cache;
    if (cache) {
      publication.commit(() => appendOutput(
        `[cache] files=${cache.filesTotal} parsed=${cache.filesParsed} `
        + `(full=${cache.filesFullParsed}, append=${cache.filesAppended}, `
        + `fallback=${cache.appendFallbacks}) reused=${cache.filesReused} `
        + `source_bytes=${cache.sourceBytesRead} rebuilt=${cache.rebuilt}`,
      ));
    }
  }
  publication.commit(() => appendOutput(`[timing] extension_total: ${result.elapsedSeconds.toFixed(3)}s`));
}

function logWarnings(
  appendOutput: (line: string) => void,
  warnings: string[],
  publication: RefreshPublication,
): void {
  for (const warning of warnings) {
    publication.commit(() => appendOutput(warning));
  }
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseCacheDiagnostics(value: unknown): DashboardCacheDiagnostics | undefined {
  if (!isRecord(value) || typeof value.rebuilt !== "boolean") {
    return undefined;
  }
  const names = [
    "files_total",
    "files_parsed",
    "files_full_parsed",
    "files_appended",
    "append_fallbacks",
    "source_bytes_read",
    "files_reused",
  ] as const;
  const values = names.map((name) => value[name]);
  if (values.some((item) => typeof item !== "number" || !Number.isSafeInteger(item) || item < 0)) {
    return undefined;
  }
  return {
    rebuilt: value.rebuilt,
    filesTotal: values[0] as number,
    filesParsed: values[1] as number,
    filesFullParsed: values[2] as number,
    filesAppended: values[3] as number,
    appendFallbacks: values[4] as number,
    sourceBytesRead: values[5] as number,
    filesReused: values[6] as number,
  };
}
