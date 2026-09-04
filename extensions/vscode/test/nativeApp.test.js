const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const { nativeAppCandidates } = require("../out/nativeApp");

test("macOS app discovery checks system and per-user Applications", () => {
  assert.deepEqual(nativeAppCandidates({}, "darwin", "/Users/test"), [
    "/Applications/Codex Usage.app",
    "/Users/test/Applications/Codex Usage.app",
  ]);
});

test("Windows app discovery follows current-user NSIS locations", () => {
  assert.deepEqual(nativeAppCandidates({ LOCALAPPDATA: "C:\\Users\\test\\AppData\\Local" }, "win32", "C:\\Users\\test"), [
    path.win32.join("C:\\Users\\test\\AppData\\Local", "Codex Usage", "codex-usage-desktop.exe"),
    path.win32.join("C:\\Users\\test\\AppData\\Local", "Codex Usage", "Codex Usage.exe"),
    path.win32.join("C:\\Users\\test\\AppData\\Local", "Programs", "Codex Usage", "codex-usage-desktop.exe"),
    path.win32.join("C:\\Users\\test\\AppData\\Local", "Programs", "Codex Usage", "Codex Usage.exe"),
  ]);
});

test("Windows app discovery uses Windows paths when LOCALAPPDATA is absent", () => {
  assert.equal(
    nativeAppCandidates({}, "win32", "C:\\Users\\test")[0],
    path.win32.join("C:\\Users\\test", "AppData", "Local", "Codex Usage", "codex-usage-desktop.exe"),
  );
});
