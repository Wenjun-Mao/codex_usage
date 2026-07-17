const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const packageJson = require("../package.json");
const { cleanOutput } = require("../scripts/clean-output");

test("clean output removes stale compiled modules recursively", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "codex-usage-clean-"));
  const out = path.join(root, "out");
  fs.mkdirSync(path.join(out, "nested"), { recursive: true });
  fs.writeFileSync(path.join(out, "syncSetupTransaction.js"), "stale");
  fs.writeFileSync(path.join(out, "nested", "stale.js"), "stale");

  cleanOutput(out);

  assert.equal(fs.existsSync(out), false);
  fs.rmSync(root, { recursive: true, force: true });
});

test("normal build cleans output before compiling", () => {
  assert.equal(packageJson.scripts.clean, "node scripts/clean-output.js");
  assert.equal(packageJson.scripts.build, "npm run clean && tsc -p .");
});
