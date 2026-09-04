const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const { npmCliPath, vsceCliPath } = require("../scripts/cliEntrypoints");
const { packageVsix } = require("../scripts/package-vsix");

test("VSIX tooling resolves JavaScript entry points instead of command shims", () => {
  assert.equal(npmCliPath(), process.env.npm_execpath);
  assert.equal(vsceCliPath(), path.join(path.dirname(require.resolve("@vscode/vsce/package.json")), "vsce"));
});

test("VSIX packaging requires npm's JavaScript entry point", () => {
  assert.throws(() => npmCliPath({}), /npm_execpath/);
});

test("VSIX packaging runs npm and vsce through Node", () => {
  const extensionRoot = path.join(path.sep, "extension");
  const releaseDirectory = path.join(path.sep, "releases");
  const calls = [];

  packageVsix("win32-x64", {
    extensionRoot,
    releaseDirectory,
    fileSystem: {
      existsSync: (candidate) => candidate === path.join(extensionRoot, "bin/win32-x64/codex-usage-agent.exe"),
      mkdirSync: () => {},
    },
    run: (...args) => calls.push(args),
    nodePath: "node",
    npmPath: "npm-cli.js",
    vscePath: "vsce.js",
  });

  assert.deepEqual(calls.map(([command]) => command), ["node", "node", "node"]);
  assert.deepEqual(calls[0][1], ["npm-cli.js", "run", "build"]);
  assert.deepEqual(calls[2][1].slice(0, 3), ["vsce.js", "package", "--target"]);
});
