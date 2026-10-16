const assert = require("node:assert/strict");
const test = require("node:test");
const { registerDiagnosticsCommand } = require("../out/diagnosticsCommand");

function setup(payload, { failure, clipboardFailure } = {}) {
  const calls = [], copied = [], notices = [], errors = [];
  let command;
  const ui = {
    commands: { registerCommand(name, callback) { assert.equal(name, "codexUsage.copyDiagnostics"); command = callback; return {}; } },
    env: { clipboard: { async writeText(text) { if (clipboardFailure) throw clipboardFailure; copied.push(text); } } },
    window: { showInformationMessage(message) { notices.push(message); }, showErrorMessage(message) { errors.push(message); } },
  };
  registerDiagnosticsCommand({ subscriptions: [] }, ui, async () => {
    if (failure) throw failure;
    return { async get(path) { calls.push(path); return payload; } };
  });
  return { run: () => command(), calls, copied, notices, errors };
}

test("Copy Diagnostics is opt-in, read-only and copies only the returned support text", async () => {
  const state = setup({ schema_version: 1, text: '{"evidence":"cached"}' });
  assert.deepEqual(state.calls, []);
  await state.run();
  assert.deepEqual(state.calls, ["/v1/allowance/diagnostics"]);
  assert.deepEqual(state.copied, ['{"evidence":"cached"}']);
  assert.equal(state.notices.length, 1);
  assert.deepEqual(state.errors, []);
});

test("invalid or oversized diagnostics do not overwrite the clipboard", async () => {
  for (const payload of [null, {}, { schema_version: 2, text: "data" },
    { schema_version: 1, text: "" }, { schema_version: 1, text: "x".repeat(48 * 1024 + 1) }]) {
    const state = setup(payload);
    await state.run();
    assert.deepEqual(state.copied, []);
    assert.equal(state.errors.length, 1);
    assert.deepEqual(state.notices, []);
  }
});

test("unavailable collector or clipboard failure reports failure, not success", async () => {
  for (const options of [{ failure: new Error("No running collector") }, { clipboardFailure: new Error("Clipboard unavailable") }]) {
    const state = setup({ schema_version: 1, text: "data" }, options);
    await state.run();
    assert.deepEqual(state.copied, []);
    assert.deepEqual(state.notices, []);
    assert.equal(state.errors.length, 1);
  }
});
