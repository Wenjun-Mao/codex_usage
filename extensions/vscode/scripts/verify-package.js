const childProcess = require("node:child_process");

const listing = childProcess.execFileSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["vsce", "ls", "--no-dependencies"],
  { cwd: process.cwd(), encoding: "utf8" },
);
const files = listing.split(/\r?\n/u).map((value) => value.trim()).filter(Boolean);
const forbidden = files.filter((file) =>
  /(^|\/)(bin|src|test)(\/|$)|\.py$|usage-cache|codex-usage-agent/iu.test(file),
);
if (forbidden.length) {
  throw new Error(`Companion package contains retired runtime files:\n${forbidden.join("\n")}`);
}
for (const required of ["out/extension.js", "package.json", "README.md"]) {
  if (!files.includes(required)) {
    throw new Error(`Companion package is missing ${required}`);
  }
}
