// Disposable real VS Code host; rendered-input acceptance is owned by Python.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const vscode = require("vscode");

exports.run = async function () {
  const root = process.env.CODEX_SPEED_ACCEPTANCE_ROOT;
  assert(root && process.env.CODEX_HOME.startsWith(root));
  const originalLoad = Module._load;
  let panel, options;
  const windowDescriptors = Object.getOwnPropertyDescriptors(vscode.window);
  windowDescriptors.createWebviewPanel = { value: (...args) => {
    options = args[3]; panel = vscode.window.createWebviewPanel(...args); return panel;
  }, enumerable: true };
  const descriptors = Object.getOwnPropertyDescriptors(vscode);
  descriptors.window = { value: Object.create(null, windowDescriptors), enumerable: true };
  const api = Object.create(null, descriptors);
  Module._load = function (request, parent, ...rest) {
    if (request === "vscode" && parent?.filename.startsWith(path.join(root, "extension"))) return api;
    return originalLoad.call(this, request, parent, ...rest);
  };
  const evidence = { synthetic_only: true, native_vscode: vscode.version };
  try {
    const extension = vscode.extensions.getExtension("wenjun-mao.codex-usage-dashboard");
    assert(extension && extension.extensionPath === path.join(root, "extension"));
    await extension.activate();
    const { AgentClient } = require(path.join(root, "extension", "out", "agentClient.js"));
    const client = await AgentClient.discover();
    const settledBy = Date.now() + 30000;
    while ((await client.get("/v1/status")).capture_running) {
      assert(Date.now() < settledBy, "synthetic startup capture did not settle");
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    await vscode.commands.executeCommand("codexUsage.openDashboard");
    assert(panel && panel.webview.html.includes("Usage &amp; Allowance Breakdown"));
    assert.equal(options.enableScripts, false);
    assert.deepEqual(options.localResourceRoots, []);
    assert(options.enableCommandUris.includes("codexUsage.navigateBreakdown"));
    assert(!panel.webview.html.includes("<script"));
    assert(panel.webview.html.includes("default-src &#39;none&#39;"));
    const before = panel.webview.html;
    const match = before.match(/command:codexUsage.navigateBreakdown\?([^"<]+)/);
    const args = JSON.parse(decodeURIComponent(match[1]))[0];
    for (const bad of [{ ...args, scope: "stale" }, { ...args, extra: 1 },
      { ...args, state: { ...args.state, day: "2099-01-01" } },
      { ...args, state: { ...args.state, detail: "project:foreign" } }]) {
      await vscode.commands.executeCommand("codexUsage.navigateBreakdown", bad);
      assert.equal(panel.webview.html, before);
    }
    evidence.script_disabled = true;
    evidence.strict_host_validation = true;
    fs.writeFileSync(path.join(root, "ready.json"), JSON.stringify(evidence));
    const deadline = Date.now() + 120000;
    while (!fs.existsSync(path.join(root, "clicked.json"))) {
      assert(Date.now() < deadline, "rendered breakdown input timed out");
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    evidence.rendered_input = JSON.parse(fs.readFileSync(path.join(root, "clicked.json"), "utf8"));
    assert(evidence.rendered_input.length >= 10);
    evidence.no_capture_command = true;
    evidence.startup_capture = "Normal bundled collector startup; synthetic-only RPC override, settled before rendered scope";
    evidence.no_scripts_or_csp_relaxation = true;
  } catch (error) {
    fs.writeFileSync(path.join(root, "failure.txt"), error.stack || String(error));
    throw error;
  } finally {
    Module._load = originalLoad;
    panel?.dispose();
    await require(path.join(root, "extension", "out", "extension.js")).deactivate();
  }
  fs.writeFileSync(path.join(root, "host-evidence.json"), JSON.stringify(evidence, null, 2));
};
