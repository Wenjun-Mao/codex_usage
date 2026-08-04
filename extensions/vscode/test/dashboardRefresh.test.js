const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  createDashboardRefreshCoordinator,
  createDashboardRefreshRequest,
  executeDashboardRefresh,
  publishDashboardRefresh,
} = require("../out/dashboardRefresh");

function requestFor(storagePath, requestId, panel = { webview: { html: "", cspSource: "vscode-resource:" } }) {
  return createDashboardRefreshRequest({
    requestId,
    panel,
    settings: {
      range: "today",
      projectKeys: [],
      theme: "auto",
      taskTransfer: { folder: "" },
      projectTransitions: { autoDetect: true },
    },
    versionLabel: "v1.0.0",
    globalStoragePath: storagePath,
  });
}

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

test("dashboard refresh requests give every report and timing sidecar a distinct path", () => {
  const first = requestFor("/tmp/codex-usage", 1);
  const second = requestFor("/tmp/codex-usage", 2);

  assert.notEqual(first.reportPath, second.reportPath);
  assert.notEqual(first.timingOutputPath, second.timingOutputPath);
  assert.match(first.reportPath, /dashboard-1\.html$/);
  assert.match(second.timingOutputPath, /dashboard-2\.timing\.json$/);
});

test("dashboard refresh publishes parsed timing phases with extension elapsed time", async (t) => {
  const storagePath = fs.mkdtempSync(path.join(__dirname, "dashboard-refresh-"));
  t.after(() => fs.rmSync(storagePath, { recursive: true, force: true }));
  const panel = { webview: { html: "", cspSource: "vscode-resource:" } };
  const request = requestFor(storagePath, 1, panel);
  const output = [];
  const result = await executeDashboardRefresh(request, {
    globalStoragePath: storagePath,
    resolveExecutable: async () => "/bin/codex-usage",
    runCodexUsage: async () => {
      await fs.promises.writeFile(request.reportPath, "<html><head></head><body><main>Report</main></body></html>");
      await fs.promises.writeFile(request.timingOutputPath, JSON.stringify({
        version: 1,
        phases_seconds: { inventory: 0.125, range_query: 0.25, total_cli: 0.5 },
        total_seconds: 0.5,
      }));
      return { stdout: "", stderr: "" };
    },
    appendOutput: (line) => output.push(line),
    setStatus: () => undefined,
  });

  assert.equal(result.kind, "success");
  assert.deepEqual(result.timing, {
    phaseSeconds: { inventory: 0.125, range_query: 0.25, total_cli: 0.5 },
    cliSeconds: 0.5,
  });
  publishDashboardRefresh(request, result, {
    appendOutput: (line) => output.push(line),
    updateStatus: () => undefined,
    showError: () => undefined,
  }, {
    isCurrent: () => true,
    commit: (sideEffect) => {
      sideEffect();
      return true;
    },
  });

  assert.match(panel.webview.html, /Loaded in \d+\.\d seconds/);
  assert.match(output.join("\n"), /inventory: 0\.125s/);
  assert.equal(output.filter((line) => line.includes("total_cli")).length, 1);
  assert.match(output.join("\n"), /extension_total: \d+\.\d{3}s/);
});

test("stale dashboard execution does not emit timing diagnostics or final status", async (t) => {
  const storagePath = fs.mkdtempSync(path.join(__dirname, "dashboard-stale-"));
  t.after(() => fs.rmSync(storagePath, { recursive: true, force: true }));
  const panel = { webview: { html: "", cspSource: "vscode-resource:" } };
  const first = requestFor(storagePath, 1, panel);
  const second = requestFor(storagePath, 2, panel);
  const firstRunStarted = deferred();
  const allowFirstRun = deferred();
  const output = [];
  const executionStatuses = [];
  const publishedStatuses = [];
  let runCount = 0;
  const coordinator = createDashboardRefreshCoordinator({
    globalStoragePath: storagePath,
    resolveExecutable: async () => "/bin/codex-usage",
    runCodexUsage: async (_executablePath, args) => {
      const outputPath = args[args.indexOf("--output") + 1];
      const timingPath = args[args.indexOf("--timing-output") + 1];
      runCount += 1;
      await fs.promises.writeFile(outputPath, `<html><head></head><body><main>Report ${runCount}</main></body></html>`);
      if (runCount === 1) {
        firstRunStarted.resolve();
        await allowFirstRun.promise;
      } else {
        await fs.promises.writeFile(timingPath, "not JSON");
      }
      return { stdout: "", stderr: "" };
    },
    appendOutput: (line) => output.push(line),
    setStatus: (label) => executionStatuses.push(label),
    updateStatus: (intent) => publishedStatuses.push(intent),
    showError: () => undefined,
  });

  const firstOutcome = coordinator.request(first);
  await firstRunStarted.promise;
  const secondOutcome = coordinator.request(second);
  allowFirstRun.resolve();

  assert.equal(await firstOutcome, "superseded");
  assert.equal(await secondOutcome, "published");
  assert.equal(runCount, 2);
  assert.equal(output.join("\n").includes(first.timingOutputPath), false);
  assert.equal(output.join("\n").includes(second.timingOutputPath), true);
  assert.deepEqual(executionStatuses, []);
  assert.deepEqual(publishedStatuses, [{ loadingKind: "initializing" }]);
  assert.match(panel.webview.html, /Report 2/);
});
