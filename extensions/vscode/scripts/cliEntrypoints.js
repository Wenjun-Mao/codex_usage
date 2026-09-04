const fs = require("node:fs");
const path = require("node:path");

function npmCliPath(environment = process.env) {
  const entrypoint = environment.npm_execpath;
  if (!entrypoint || !fs.existsSync(entrypoint)) {
    throw new Error("npm_execpath must identify npm's JavaScript entry point when packaging a VSIX.");
  }
  return entrypoint;
}

function vsceCliPath() {
  const entrypoint = path.join(path.dirname(require.resolve("@vscode/vsce/package.json")), "vsce");
  if (!fs.existsSync(entrypoint)) {
    throw new Error("The installed @vscode/vsce package does not provide its JavaScript entry point.");
  }
  return entrypoint;
}

module.exports = { npmCliPath, vsceCliPath };
