// File-controlled disposable host: production activation/config handler, no webview scripts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const vscode = require('vscode');
exports.run = async function () {
  const root = process.env.CODEX_SPEED_ACCEPTANCE_ROOT;
  assert(root && process.env.CODEX_HOME.startsWith(root));
  const original = Module._load;
  let panel, activeSerial = 0, committedStarted;
  const window = Object.getOwnPropertyDescriptors(vscode.window);
  window.createWebviewPanel = { value: (...args) => {
    assert.equal(args[3].enableScripts, false);
    assert.deepEqual(args[3].localResourceRoots, []);
    panel = vscode.window.createWebviewPanel(...args); return panel;
  }, enumerable: true };
  const workspace = Object.getOwnPropertyDescriptors(vscode.workspace);
  workspace.onDidChangeConfiguration = { value: (listener, thisArgs, disposables) =>
    vscode.workspace.onDidChangeConfiguration(event => {
      if (activeSerial && event.affectsConfiguration('codexUsage.theme')) {
        committedStarted = Date.now();
        fs.writeFileSync(path.join(root, 'started.json'), JSON.stringify({ serial: activeSerial, started: committedStarted,
          origin: 'production configuration listener receives committed theme event' }));
      }
      return listener.call(thisArgs, event);
    }, undefined, disposables), enumerable: true };
  const descriptors = Object.getOwnPropertyDescriptors(vscode);
  descriptors.workspace = { value: Object.create(null, workspace), enumerable: true };
  descriptors.window = { value: Object.create(null, window), enumerable: true };
  const api = Object.create(null, descriptors);
  Module._load = function (name, parent, ...rest) {
    if (name === 'vscode' && parent?.filename.startsWith(path.join(root, 'extension'))) return api;
    return original.call(this, name, parent, ...rest);
  };
  const write = (name, data) => fs.writeFileSync(path.join(root, name + '.json'), JSON.stringify(data));
  const pause = () => new Promise(resolve => setTimeout(resolve, 10));
  try {
    const extension = vscode.extensions.getExtension('wenjun-mao.codex-usage-dashboard');
    assert.equal(extension.extensionPath, path.join(root, 'extension'));
    await extension.activate();
    await vscode.commands.executeCommand('codexUsage.openDashboard');
    write('ready', { theme: 'night' });
    let serial = 0;
    while (!fs.existsSync(path.join(root, 'done.json'))) {
      const file = path.join(root, 'request.json');
      if (fs.existsSync(file)) {
        const request = JSON.parse(fs.readFileSync(file));
        if (request.serial > serial) {
          serial = request.serial;
          activeSerial = serial;
          committedStarted = undefined;
          await vscode.workspace.getConfiguration('codexUsage').update('theme', request.theme, vscode.ConfigurationTarget.Global);
          while (!panel.webview.html.includes(`data-codex-theme="${request.theme}"`) || !panel.webview.html.includes('Usage &amp; Allowance Breakdown')) await pause();
          assert(committedStarted, 'Committed configuration event was not observed');
          write('assigned', { serial, started: committedStarted, assigned: Date.now() });
        }
      }
      await pause();
    }
  } catch (error) { fs.writeFileSync(path.join(root, 'failure.txt'), error.stack); throw error; }
  finally {
    Module._load = original;
    panel?.dispose();
    await require(path.join(root, 'extension/out/extension.js')).deactivate();
  }
};
