const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  createDashboardRefreshCoordinator,
  createDashboardRefreshRequest,
  dashboardLoadingKind,
  executeDashboardRefresh,
  publishDashboardRefresh,
} = require("../out/dashboardRefresh");
const { legacyCacheDbPaths } = require("../out/core");

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

test("dashboard refresh marks schema-6 cache storage as rebuilding", async (t) => {
  const storagePath = fs.mkdtempSync(path.join(__dirname, "dashboard-schema-6-"));
  t.after(() => fs.rmSync(storagePath, { recursive: true, force: true }));
  const legacyPath = legacyCacheDbPaths(storagePath)[0];
  fs.mkdirSync(path.dirname(legacyPath), { recursive: true });
  fs.writeFileSync(legacyPath, "schema-6");

  assert.equal(await dashboardLoadingKind(storagePath), "rebuilding");
});

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
        version: 2,
        phases_seconds: { inventory: 0.125, range_query: 0.25, total_cli: 0.5 },
        total_seconds: 0.5,
        cache: {
          rebuilt: false,
          files_total: 10,
          files_parsed: 2,
          files_full_parsed: 1,
          files_appended: 1,
          append_fallbacks: 0,
          source_bytes_read: 131072,
          files_reused: 8,
        },
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
    cache: {
      rebuilt: false,
      filesTotal: 10,
      filesParsed: 2,
      filesFullParsed: 1,
      filesAppended: 1,
      appendFallbacks: 0,
      sourceBytesRead: 131072,
      filesReused: 8,
    },
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
  assert.match(output.join("\n"), /\[cache\].*full=1, append=1, fallback=0/);
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
