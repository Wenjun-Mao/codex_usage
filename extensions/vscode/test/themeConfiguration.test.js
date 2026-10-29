const assert = require('node:assert/strict');
const test = require('node:test');
const Module = require('node:module');

// Exercise the shipped activation, commands, configuration listener and decorator.
async function host(t, windowsPaths = false) {
  const commands = new Map(), requests = [], renders = [], progress = [], settings = { theme: 'night', range: '30d' };
  const state = new Map();
  let changed, disposed, pick, fail, pending;
  const status = { ledger_revision: 1, capabilities: ['image-generation-accounting', 'observed-output-speed-v1', 'usage-allowance-breakdown-v1', 'on-demand-allowance-history-v1'], speed: { metric_version: 1 }, coverage: { pending_files: 0, stale_sources: 0 } };
  const client = { async get(url) {
    requests.push(url);
    if (url === '/v1/status') return status;
    if (url.startsWith('/v1/storage/')) return { trees: [], totals: {}, projects: [] };
    if (fail) throw new Error('transport unavailable');
    const report = { html: '<!DOCTYPE html><html data-codex-theme="auto"><head></head><body><main>Accounting 123</main></body></html>', status, ledger_revision: status.ledger_revision, elapsed_seconds: .01, cache_hit: true };
    const historyState = { period_page: 0, uncertain_page: 0, kind: '', index: -1, fit_page: 0, capture_page: 0, capture_order: 'newest' };
    report.allowance_navigation = { scope: 'a'.repeat(64), state: historyState, actions: [{ scope: 'a'.repeat(64), state: historyState }], deferred: new URLSearchParams(url.split('?')[1]).get('allowance_history') === 'deferred' };
    if (pending) return pending(report);
    return report;
  }};
  const panel = { visible: true, reveal() {}, onDidDispose(fn) { disposed = fn; }, webview: { cspSource: 'fixture', get html() { return renders.at(-1); }, set html(value) { renders.push(value); } } };
  const api = {
    StatusBarAlignment: { Right: 1 }, ViewColumn: { One: 1 }, ConfigurationTarget: { Global: 1 }, ProgressLocation: { Notification: 1 },
    commands: { registerCommand(name, fn) { commands.set(name, fn); return {}; } },
    window: { createOutputChannel: () => ({ appendLine() {} }), createStatusBarItem: () => ({ show() {} }), createWebviewPanel: (...args) => { assert.equal(args[3].enableScripts, false); assert.deepEqual(args[3].localResourceRoots, []); return panel; }, showQuickPick: async () => pick,
      withProgress: async (options, operation) => { progress.push(options.title); return operation(); } },
    workspace: { onDidChangeConfiguration(fn) { changed = fn; return {}; }, getConfiguration: () => ({ get: (key, fallback) => settings[key] ?? fallback, async update(key, value) { settings[key] = value; await changed({ affectsConfiguration: name => name === 'codexUsage' || name === `codexUsage.${key}` }); } }) },
  };
  const load = Module._load;
  Module._load = function(name, parent, ...rest) {
    if (name === 'vscode') return api;
    if (name === './agentSupervisor') {
      const filename = windowsPaths ? parent.filename.replaceAll('/', '\\') : parent.filename;
      assert.match(filename, /[/\\]out[/\\]extension\.js$/);
      return { AgentSupervisor: class { acquire() { return client; } async stopManagedAgent() {} } };
    }
    return load.call(this, name, parent, ...rest);
  };
  const target = require.resolve('../out/extension');
  delete require.cache[target];
  const extension = require(target);
  t.after(async () => { await extension.deactivate(); Module._load = load; delete require.cache[target]; });
  await extension.activate({ subscriptions: [], extension: { packageJSON: { version: 'test' } }, globalState: { get: (key, fallback) => state.get(key) ?? fallback }, extensionUri: { fsPath: '/fixture' } });
  async function settle() { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); }
  return { commands, requests, renders, progress, settings, state, status, panel, settle, change: async (key, value) => { await api.workspace.getConfiguration().update(key, value); await settle(); }, pick: value => { pick = value; }, fail: value => { fail = value; }, pending: fn => { pending = fn; }, dispose: () => disposed() };
}

test('initial Night and real configuration changes use one collector theme with local Day/Auto presentation', async t => {
  const h = await host(t, true);
  await h.commands.get('codexUsage.openDashboard')();
  assert.match(h.panel.webview.html, /data-codex-theme="night"/);
  for (const theme of ['day', 'auto', 'night']) {
    const previousRenders = h.renders.length;
    await h.change('theme', theme);
    assert.match(h.panel.webview.html, new RegExp(`data-codex-theme="${theme}"`));
    assert.match(h.panel.webview.html, /Accounting 123/);
    assert.equal(h.renders.length, previousRenders + 1, 'theme updates keep the report visible until final replacement');
  }
  assert.equal(h.requests.filter(url => url.startsWith('/v1/report?')).length, 4);
  for (const url of h.requests.filter(url => url.startsWith('/v1/report?'))) assert.equal(new URLSearchParams(url.split('?')[1]).get('theme'), 'auto');
  assert(!h.requests.some(url => /capture/.test(url)));
});

test('theme picker cancellation and selection use persisted configuration; disposed panels ignore changes', async t => {
  const h = await host(t);
  await h.commands.get('codexUsage.openDashboard')();
  const count = h.requests.length;
  await h.commands.get('codexUsage.selectTheme')();
  assert.equal(h.requests.length, count);
  h.pick({ theme: 'day' });
  await h.commands.get('codexUsage.selectTheme')();
  await h.settle();
  assert.equal(h.settings.theme, 'day');
  assert.match(h.panel.webview.html, /data-codex-theme="day"/);
  h.dispose();
  const closed = h.requests.length;
  await h.change('theme', 'night');
  assert.equal(h.requests.length, closed);
});

test('rapid configuration replies cannot replace the latest display; transport errors retain selected theme', async t => {
  const h = await host(t);
  await h.commands.get('codexUsage.openDashboard')();
  const replies = [];
  h.pending(report => new Promise(resolve => replies.push(() => resolve(report))));
  await h.change('theme', 'day');
  await h.change('theme', 'auto');
  replies[1](); await h.settle();
  replies[0](); await h.settle();
  assert.match(h.panel.webview.html, /data-codex-theme="auto"/);
  h.pending(undefined); h.fail(true);
  await h.change('theme', 'night');
  assert.match(h.panel.webview.html, /data-codex-theme="night"/);
  assert.match(h.panel.webview.html, /transport unavailable/);
});


test('custom range and project scope survive theme selection, revision refresh, and reopen', async t => {
  const h = await host(t);
  h.settings.range = 'custom';
  h.state.set('customReportRange', { startDate: '2026-10-01', endDate: '2026-10-10' });
  h.state.set('selectedProjectKeys', ['/synthetic/project-b', '/synthetic/project-a']);
  await h.commands.get('codexUsage.openDashboard')();
  await h.change('theme', 'day');
  h.status.ledger_revision++;
  await h.change('theme', 'auto');
  h.dispose();
  await h.commands.get('codexUsage.openDashboard')();
  assert.match(h.panel.webview.html, /data-codex-theme="auto"/);
  for (const url of h.requests.filter(url => url.startsWith('/v1/report?'))) {
    const query = new URLSearchParams(url.split('?')[1]);
    assert.equal(query.get('theme'), 'auto');
    assert.equal(query.get('range'), 'custom');
    assert.equal(query.get('start_date'), '2026-10-01');
    assert.equal(query.get('end_date'), '2026-10-10');
    assert.deepEqual(query.getAll('project_key'), ['/synthetic/project-b', '/synthetic/project-a']);
  }
});

test('issued history load shows progress and failures, then retries requested history and resets on reopen', async t => {
  const h = await host(t);
  await h.commands.get('codexUsage.openDashboard')();
  const action = { scope: 'a'.repeat(64), state: { period_page: 0, uncertain_page: 0, kind: '', index: -1, fit_page: 0, capture_page: 0, capture_order: 'newest' } };
  h.fail(true);
  await h.commands.get('codexUsage.navigateAllowanceHistory')(action);
  assert.deepEqual(h.progress, ['Loading allowance history']);
  assert.match(h.panel.webview.html, /transport unavailable/);
  assert.match(h.panel.webview.html, /command:codexUsage.refreshDashboard/);
  h.fail(false);
  await h.commands.get('codexUsage.refreshDashboard')();
  let query = new URLSearchParams(h.requests.at(-1).split('?')[1]);
  assert.equal(query.get('allowance_history'), 'requested');
  assert(!query.has('allowance_action'));
  assert.match(h.panel.webview.html, /Accounting 123/);
  h.dispose();
  await h.commands.get('codexUsage.openDashboard')();
  query = new URLSearchParams(h.requests.at(-1).split('?')[1]);
  assert.equal(query.get('allowance_history'), 'deferred');
});
