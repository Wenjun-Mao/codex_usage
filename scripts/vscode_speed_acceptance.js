// Run only in the disposable extension host created by check_speed_webview.py.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const vscode = require("vscode");

exports.run = async function () {
  const root = process.env.CODEX_SPEED_ACCEPTANCE_ROOT;
  assert(root && process.env.CODEX_HOME.startsWith(root));
  fs.writeFileSync(path.join(root, "started.json"), JSON.stringify({ root }));
  const originalLoad = Module._load;
  let panel;
  let options;
  const createPanel = (...args) => {
    options = args[3];
    panel = vscode.window.createWebviewPanel(...args);
    return panel;
  };
  const windowDescriptors = Object.getOwnPropertyDescriptors(vscode.window);
  windowDescriptors.createWebviewPanel = { value: createPanel, enumerable: true };
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
    await vscode.commands.executeCommand("codexUsage.openDashboard");
    assert(panel && panel.webview.html.includes("Observed Output Speed"));
    assert.equal(options.enableScripts, false);
    assert.deepEqual(options.localResourceRoots, []);
    assert(options.enableCommandUris.includes("codexUsage.navigateSpeed"));
    assert(!panel.webview.html.includes("<script"));
    assert(panel.webview.html.includes("default-src &#39;none&#39;"));
    const before = panel.webview.html;
    await vscode.commands.executeCommand("codexUsage.navigateSpeed", { scope: "stale", granularity: "hourly", windowStart: "2026-10-02" });
    assert.equal(panel.webview.html, before);
    evidence.script_disabled = true;
    evidence.stale_command_rejected = true;
    fs.writeFileSync(path.join(root, "ready.json"), JSON.stringify(evidence));
    const hostOnly = process.env.CODEX_SPEED_HOST_ONLY === "true";
    if (hostOnly) {
      const uri = panel.webview.html.match(/command:codexUsage.navigateSpeed\?([^"<]+)[^>]*>Hourly<\/a>/)[1];
      const args = JSON.parse(decodeURIComponent(uri))[0];
      await vscode.commands.executeCommand("codexUsage.navigateSpeed", args);
    }
    const deadline = Date.now() + 90000;
    while (!hostOnly && !fs.existsSync(path.join(root, "clicked.json"))) {
      assert(Date.now() < deadline, "native command-link click timed out");
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(panel.webview.html.includes('class="speed-window"'));
    const selected = panel.webview.html.match(/command:codexUsage.navigateSpeed\?([^"<]+)/g);
    const query = selected.map(uri => JSON.parse(decodeURIComponent(uri.split("?")[1]))[0]);
    const hourly = query.find(value => value.granularity === "hourly");
    assert(hourly);
    await vscode.commands.executeCommand("codexUsage.captureNow");
    assert(panel.webview.html.includes('class="speed-window"'));
    const refreshed = panel.webview.html.match(/command:codexUsage.navigateSpeed\?([^"<]+)/g)
      .map(uri => JSON.parse(decodeURIComponent(uri.split("?")[1]))[0]);
    assert(refreshed.some(value => value.granularity === "hourly" && value.windowStart === hourly.windowStart));
    evidence.native_link_navigation = !hostOnly;
    evidence.native_host_command_navigation = true;
    evidence.capture_preserves_window = true;
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
