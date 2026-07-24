const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");

const calls = {
  activations: 0,
  appx: [],
  configuration: [],
  extension: [],
  readdirs: [],
  stats: [],
};

function resetCalls() {
  calls.activations = 0;
  for (const value of Object.values(calls)) {
    if (Array.isArray(value)) value.length = 0;
  }
}

const fakeVscode = {
  extensions: {
    getExtension(id) {
      calls.extension.push(id);
      return {
        extensionPath: "/extensions/openai.chatgpt",
        activate() {
          calls.activations += 1;
        },
      };
    },
  },
  workspace: {
    getConfiguration(section) {
      calls.configuration.push(section);
      return {
        get(key) {
          calls.configuration.push(key);
          return "/configured/codex";
        },
      };
    },
  },
};

const originalLoad = Module._load;
Module._load = function loadWithVscodeFake(request, parent, isMain) {
  return request === "vscode" ? fakeVscode : originalLoad.call(this, request, parent, isMain);
};
const { createCodexTaskRegistrar } = require("../out/codexRegistrationVscode");
Module._load = originalLoad;

function dependencies(overrides = {}) {
  return {
    platform: "darwin",
    arch: "arm64",
    env: { PATH: "/bin" },
    homeDir: () => "/Users/alice",
    async stat(candidate) {
      calls.stats.push(candidate);
      return { isFile: () => candidate === "/candidate" };
    },
    async readdir(directory, options) {
      calls.readdirs.push([directory, options]);
      return [{ name: "child", isDirectory: () => true }];
    },
    async executeFile(file, args, options) {
      calls.appx.push([file, args, options]);
      return { stdout: " C:\\Program Files\\WindowsApps\\OpenAI.Codex \\n" };
    },
    async discoverCandidates(context, probe) {
      return [{ executablePath: "codex", source: "path" }];
    },
    async registerTasks(options) {
      return {
        attemptedThreadIds: [...options.threadIds],
        registeredThreadIds: [...options.threadIds],
        failures: [],
        executable: options.candidates[0],
      };
    },
    ...overrides,
  };
}

test("reads VS Code Codex settings and passes runtime context to discovery without activating the official extension", async () => {
  resetCalls();
  let discovered;
  let registration;
  const registrar = createCodexTaskRegistrar({
    extensionVersion: "0.1.37",
    dependencies: dependencies({
      async discoverCandidates(context, probe) {
        discovered = context;
        assert.equal(await probe.pathExists("/candidate"), true);
        assert.deepEqual(await probe.listDirectoryNames("/candidate-dir"), ["child"]);
        return [{ executablePath: "/candidate", source: "desktop-app" }];
      },
      async registerTasks(options) {
        registration = options;
        return {
          attemptedThreadIds: ["task-a"],
          registeredThreadIds: ["task-a"],
          failures: [],
          executable: options.candidates[0],
        };
      },
    }),
  });

  const result = await registrar(["task-a"]);

  assert.deepEqual(calls.configuration, ["chatgpt", "cliExecutable"]);
  assert.deepEqual(calls.extension, ["openai.chatgpt"]);
  assert.equal(calls.activations, 0);
  assert.deepEqual(discovered, {
    platform: "darwin",
    arch: "arm64",
    env: { PATH: "/bin" },
    homeDir: "/Users/alice",
    cliOverride: "/configured/codex",
    officialExtensionPath: "/extensions/openai.chatgpt",
  });
  assert.deepEqual(calls.stats, ["/candidate"]);
  assert.deepEqual(calls.readdirs, [["/candidate-dir", { withFileTypes: true }]]);
  assert.equal(registration.extensionVersion, "0.1.37");
  assert.deepEqual(registration.candidates, [{ executablePath: "/candidate", source: "desktop-app" }]);
  assert.deepEqual(result.registeredThreadIds, ["task-a"]);
});

test("treats inaccessible filesystem probes as absent and never queries AppX outside Windows", async () => {
  resetCalls();
  const registrar = createCodexTaskRegistrar({
    extensionVersion: "0.1.37",
    dependencies: dependencies({
      async stat(candidate) {
        calls.stats.push(candidate);
        throw new Error("access denied");
      },
      async readdir(directory, options) {
        calls.readdirs.push([directory, options]);
        throw new Error("access denied");
      },
      async discoverCandidates(_context, probe) {
        assert.equal(await probe.pathExists("/protected/codex"), false);
        assert.deepEqual(await probe.listDirectoryNames("/protected"), []);
        assert.equal(await probe.windowsAppxInstallLocation(), undefined);
        return [];
      },
    }),
  });

  await registrar(["task-a"]);

  assert.deepEqual(calls.stats, ["/protected/codex"]);
  assert.deepEqual(calls.readdirs, [["/protected", { withFileTypes: true }]]);
  assert.deepEqual(calls.appx, []);
});

test("queries Windows AppX with direct PowerShell argv and ignores unavailable command output", async () => {
  resetCalls();
  const locations = [];
  const registrar = createCodexTaskRegistrar({
    extensionVersion: "0.1.37",
    dependencies: dependencies({
      platform: "win32",
      arch: "x64",
      async discoverCandidates(_context, probe) {
        locations.push(await probe.windowsAppxInstallLocation());
        return [];
      },
      async executeFile(file, args, options) {
        calls.appx.push([file, args, options]);
        throw new Error("access denied");
      },
    }),
  });

  await registrar(["task-a"]);

  assert.deepEqual(locations, [undefined]);
  assert.deepEqual(calls.appx, [[
    "powershell.exe",
    [
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      "(Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1 -ExpandProperty InstallLocation)",
    ],
    { shell: false, windowsHide: true, timeout: 5_000 },
  ]]);
});

test("treats a timed-out Windows AppX probe as unavailable", async () => {
  resetCalls();
  const locations = [];
  const registrar = createCodexTaskRegistrar({
    extensionVersion: "0.1.37",
    dependencies: dependencies({
      platform: "win32",
      arch: "x64",
      async discoverCandidates(_context, probe) {
        locations.push(await probe.windowsAppxInstallLocation());
        return [];
      },
      async executeFile(file, args, options) {
        calls.appx.push([file, args, options]);
        throw Object.assign(new Error("command timed out"), { code: "ETIMEDOUT" });
      },
    }),
  });

  await registrar(["task-a"]);

  assert.deepEqual(locations, [undefined]);
  assert.equal(calls.appx.length, 1);
  assert.deepEqual(calls.appx[0][2], { shell: false, windowsHide: true, timeout: 5_000 });
});

test("returns failures for every requested task without registering when discovery finds no candidates", async () => {
  resetCalls();
  let registrationAttempts = 0;
  const registrar = createCodexTaskRegistrar({
    extensionVersion: "0.1.37",
    dependencies: dependencies({
      async discoverCandidates() {
        return [];
      },
      async registerTasks() {
        registrationAttempts += 1;
        throw new Error("registration must not be attempted");
      },
    }),
  });

  const result = await registrar(["task-a", "task-b"]);

  assert.equal(registrationAttempts, 0);
  assert.deepEqual(result, {
    attemptedThreadIds: ["task-a", "task-b"],
    registeredThreadIds: [],
    failures: [
      { threadId: "task-a", message: "No Codex executable candidate was available" },
      { threadId: "task-b", message: "No Codex executable candidate was available" },
    ],
  });
});

test("returns the app-server's structured failure when no candidate initializes", async () => {
  resetCalls();
  const failure = {
    attemptedThreadIds: ["task-a"],
    registeredThreadIds: [],
    failures: [{ threadId: "task-a", message: "Codex app-server initialization timed out" }],
  };
  const registrar = createCodexTaskRegistrar({
    extensionVersion: "0.1.37",
    dependencies: dependencies({
      async discoverCandidates() {
        return [{ executablePath: "codex", source: "path" }];
      },
      async registerTasks() {
        return failure;
      },
    }),
  });

  const result = await registrar(["task-a"]);

  assert.equal(result, failure);
});
