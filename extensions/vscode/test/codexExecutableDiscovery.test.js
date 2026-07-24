const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const { discoverCodexExecutableCandidates } = require("../out/codexExecutableDiscovery");

function createProbe({ existing = [], directories = {}, appxLocation, inaccessible = [] } = {}) {
  const blocked = new Set(inaccessible);
  const present = new Set(existing);
  return {
    async pathExists(candidate) {
      if (blocked.has(candidate)) {
        throw new Error(`Inaccessible path: ${candidate}`);
      }
      return present.has(candidate);
    },
    async listDirectoryNames(directory) {
      if (blocked.has(directory)) {
        throw new Error(`Inaccessible directory: ${directory}`);
      }
      return directories[directory] ?? [];
    },
    async windowsAppxInstallLocation() {
      if (blocked.has("appx")) {
        throw new Error("Inaccessible AppX location");
      }
      return appxLocation;
    },
  };
}

function macContext(overrides = {}) {
  return {
    platform: "darwin",
    arch: "arm64",
    env: {},
    homeDir: "/Users/alice",
    ...overrides,
  };
}

function windowsContext(overrides = {}) {
  return {
    platform: "win32",
    arch: "x64",
    env: { LOCALAPPDATA: "C:\\Users\\Alice\\AppData\\Local" },
    homeDir: "C:\\Users\\Alice",
    ...overrides,
  };
}

test("orders an explicit override before the official macOS extension and desktop installations", async () => {
  const extensionExecutable = "/extensions/openai.chatgpt/bin/macos-aarch64/codex";
  const systemApp = "/Applications/ChatGPT.app/Contents/Resources/codex";
  const userApp = "/Users/alice/Applications/ChatGPT.app/Contents/Resources/codex";
  const candidates = await discoverCodexExecutableCandidates(
    macContext({ cliOverride: "/custom/codex", officialExtensionPath: "/extensions/openai.chatgpt" }),
    createProbe({ existing: [extensionExecutable, systemApp, userApp] }),
  );

  assert.deepEqual(candidates, [
    { executablePath: "/custom/codex", source: "cli-override" },
    { executablePath: extensionExecutable, source: "official-vscode-extension" },
    { executablePath: systemApp, source: "desktop-app" },
    { executablePath: userApp, source: "desktop-app" },
    { executablePath: "codex", source: "path" },
  ]);
});

test("includes only existing fixed macOS candidates", async () => {
  const extensionExecutable = "/extensions/openai.chatgpt/bin/macos-aarch64/codex";
  const candidates = await discoverCodexExecutableCandidates(
    macContext({ officialExtensionPath: "/extensions/openai.chatgpt" }),
    createProbe({ existing: [extensionExecutable] }),
  );

  assert.deepEqual(candidates, [
    { executablePath: extensionExecutable, source: "official-vscode-extension" },
    { executablePath: "codex", source: "path" },
  ]);
});

test("discovers Windows extension, writable desktop copies, sorted children, and AppX before PATH", async () => {
  const win = path.win32;
  const localAppData = "C:\\Users\\Alice\\AppData\\Local";
  const extensionExecutable = win.join("C:\\extensions\\openai.chatgpt", "bin", "windows-x86_64", "codex.exe");
  const codexRoot = win.join(localAppData, "OpenAI", "Codex", "bin");
  const storeRoot = win.join(
    localAppData,
    "Packages",
    "OpenAI.Codex_2p2nqsd0c76g0",
    "LocalCache",
    "Local",
    "OpenAI",
    "Codex",
    "bin",
  );
  const appxExecutable = win.join("C:\\Program Files\\WindowsApps\\OpenAI.Codex", "app", "resources", "codex.exe");
  const candidates = await discoverCodexExecutableCandidates(
    windowsContext({ officialExtensionPath: "C:\\extensions\\openai.chatgpt" }),
    createProbe({
      existing: [
        extensionExecutable,
        win.join(codexRoot, "codex.exe"),
        win.join(codexRoot, "1.10.0", "codex.exe"),
        win.join(codexRoot, "1.2.0", "codex.exe"),
        win.join(storeRoot, "hash-b", "codex.exe"),
        win.join(storeRoot, "hash-a", "codex.exe"),
        appxExecutable,
      ],
      directories: {
        [codexRoot]: ["1.10.0", "1.2.0"],
        [storeRoot]: ["hash-b", "hash-a"],
      },
      appxLocation: "C:\\Program Files\\WindowsApps\\OpenAI.Codex",
    }),
  );

  assert.deepEqual(candidates, [
    { executablePath: extensionExecutable, source: "official-vscode-extension" },
    { executablePath: win.join(codexRoot, "codex.exe"), source: "desktop-app" },
    { executablePath: win.join(codexRoot, "1.10.0", "codex.exe"), source: "desktop-app" },
    { executablePath: win.join(codexRoot, "1.2.0", "codex.exe"), source: "desktop-app" },
    { executablePath: win.join(storeRoot, "hash-a", "codex.exe"), source: "desktop-app" },
    { executablePath: win.join(storeRoot, "hash-b", "codex.exe"), source: "desktop-app" },
    { executablePath: appxExecutable, source: "desktop-app" },
    { executablePath: "codex.exe", source: "path" },
  ]);
});

test("continues after inaccessible Windows desktop and AppX probes", async () => {
  const win = path.win32;
  const localAppData = "C:\\Users\\Alice\\AppData\\Local";
  const codexRoot = win.join(localAppData, "OpenAI", "Codex", "bin");
  const storeRoot = win.join(
    localAppData,
    "Packages",
    "OpenAI.Codex_2p2nqsd0c76g0",
    "LocalCache",
    "Local",
    "OpenAI",
    "Codex",
    "bin",
  );
  const candidates = await discoverCodexExecutableCandidates(
    windowsContext(),
    createProbe({
      existing: [win.join(codexRoot, "codex.exe")],
      inaccessible: [storeRoot, "appx"],
    }),
  );

  assert.deepEqual(candidates, [
    { executablePath: win.join(codexRoot, "codex.exe"), source: "desktop-app" },
    { executablePath: "codex.exe", source: "path" },
  ]);
});

test("discovers AppX after writable desktop locations even when LOCALAPPDATA is unavailable", async () => {
  const win = path.win32;
  const appxLocation = "C:\\Program Files\\WindowsApps\\OpenAI.Codex";
  const appxExecutable = win.join(appxLocation, "app", "resources", "codex.exe");
  const candidates = await discoverCodexExecutableCandidates(
    windowsContext({ env: {} }),
    createProbe({ existing: [appxExecutable], appxLocation }),
  );

  assert.deepEqual(candidates, [
    { executablePath: appxExecutable, source: "desktop-app" },
    { executablePath: "codex.exe", source: "path" },
  ]);
});

test("skips an inaccessible AppX executable probe and retains the Windows PATH candidate", async () => {
  const win = path.win32;
  const appxLocation = "C:\\Program Files\\WindowsApps\\OpenAI.Codex";
  const appxExecutable = win.join(appxLocation, "app", "resources", "codex.exe");
  const checkedPaths = [];
  const candidates = await discoverCodexExecutableCandidates(
    windowsContext({ env: {} }),
    {
      async pathExists(candidate) {
        checkedPaths.push(candidate);
        throw new Error(`Inaccessible path: ${candidate}`);
      },
      async listDirectoryNames() {
        return [];
      },
      async windowsAppxInstallLocation() {
        return appxLocation;
      },
    },
  );

  assert.deepEqual(candidates, [{ executablePath: "codex.exe", source: "path" }]);
  assert.deepEqual(checkedPaths, [appxExecutable]);
});

test("deduplicates lexically equivalent native Windows paths while preserving the first source", async () => {
  const extensionExecutable = "C:\\Extensions\\OpenAI.ChatGPT\\bin\\windows-x86_64\\codex.exe";
  const candidates = await discoverCodexExecutableCandidates(
    windowsContext({
      cliOverride: "c:/extensions/openai.chatgpt/bin/windows-x86_64/../windows-x86_64/CODEX.EXE",
      officialExtensionPath: "C:\\Extensions\\OpenAI.ChatGPT",
    }),
    createProbe({ existing: [extensionExecutable] }),
  );

  assert.deepEqual(candidates, [
    {
      executablePath: "c:/extensions/openai.chatgpt/bin/windows-x86_64/../windows-x86_64/CODEX.EXE",
      source: "cli-override",
    },
    { executablePath: "codex.exe", source: "path" },
  ]);
});

test("deduplicates lexically equivalent native macOS paths while preserving the first source", async () => {
  const systemApp = "/Applications/ChatGPT.app/Contents/Resources/codex";
  const candidates = await discoverCodexExecutableCandidates(
    macContext({ cliOverride: "/Applications/ChatGPT.app/Contents/Resources/../Resources/codex" }),
    createProbe({ existing: [systemApp] }),
  );

  assert.deepEqual(candidates, [
    {
      executablePath: "/Applications/ChatGPT.app/Contents/Resources/../Resources/codex",
      source: "cli-override",
    },
    { executablePath: "codex", source: "path" },
  ]);
});

test("rejects unsupported platform and architecture pairs before invoking probes", async () => {
  const probe = createProbe();

  await assert.rejects(
    discoverCodexExecutableCandidates(macContext({ arch: "x64" }), probe),
    /Unsupported Codex executable discovery platform: darwin x64/,
  );
  await assert.rejects(
    discoverCodexExecutableCandidates(windowsContext({ platform: "linux" }), probe),
    /Unsupported Codex executable discovery platform: linux x64/,
  );

  const calls = { pathExists: 0, listDirectoryNames: 0, windowsAppxInstallLocation: 0 };
  await assert.rejects(
    discoverCodexExecutableCandidates(windowsContext({ arch: "arm64" }), {
      async pathExists() {
        calls.pathExists += 1;
        return false;
      },
      async listDirectoryNames() {
        calls.listDirectoryNames += 1;
        return [];
      },
      async windowsAppxInstallLocation() {
        calls.windowsAppxInstallLocation += 1;
        return undefined;
      },
    }),
    /Unsupported Codex executable discovery platform: win32 arm64/,
  );
  assert.deepEqual(calls, { pathExists: 0, listDirectoryNames: 0, windowsAppxInstallLocation: 0 });
});
