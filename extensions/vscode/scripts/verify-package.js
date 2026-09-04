const childProcess = require("node:child_process");
const { verifyPackageFiles } = require("./packageContent");

const targetIndex = process.argv.indexOf("--target");
const target = targetIndex === -1 ? undefined : process.argv[targetIndex + 1];
if (!target) throw new Error("verify-package requires --target darwin-arm64 or --target win32-x64");

const listing = childProcess.execFileSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["vsce", "ls", "--no-dependencies"],
  { cwd: process.cwd(), encoding: "utf8" },
);
const files = listing.split(/\r?\n/u).map((value) => value.trim()).filter(Boolean);
verifyPackageFiles(files, target);
