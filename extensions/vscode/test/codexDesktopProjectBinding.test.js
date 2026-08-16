const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  createCodexDesktopProjectBinder,
  DesktopProjectBindingError,
} = require("../out/codexDesktopProjectBinding");
const {
  canonicalPath,
  desktopStatePath,
  exactlyMatchingProjectId,
  normalizeDesktopProjectPath,
} = require("../out/codexDesktopBindingSupport");

const TASK_A = "019db09f-a9e0-7d93-a8b8-7697d67ad5bc";
const TASK_B = "019db5c7-5771-7512-9dc7-dc2ba033f712";

test("missing Desktop state preserves the VS Code-only path", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "codex-binding-missing-"));
  const binder = createCodexDesktopProjectBinder({
    dependencies: {
      env: { CODEX_HOME: path.join(root, "missing") },
      inspectDesktop: async () => { throw new Error("must not inspect"); },
    },
  });
  assert.deepEqual(await binder.preflight({ destinationPath: root, threadIds: [TASK_A] }), {
    mode: "not-applicable",
    threadIds: [TASK_A],
  });
});

test("preflight blocks a running or indeterminate Desktop before state mutation", async () => {
  for (const processState of [
    { status: "running" },
    { status: "unknown", reason: "probe failed" },
  ]) {
    const fixture = await bindingFixture();
    const binder = fixture.binder({ inspectDesktop: async () => processState });
    await assert.rejects(
      binder.preflight({ destinationPath: fixture.projectRoot, threadIds: [TASK_A] }),
      (error) => error instanceof DesktopProjectBindingError &&
        error.code === (processState.status === "running" ? "desktop-running" : "desktop-process-unknown"),
    );
    assert.deepEqual(JSON.parse(await fs.readFile(fixture.statePath, "utf8")), fixture.state);
  }
});

test("preflight fails closed when Desktop state identity is unavailable", async () => {
  const fixture = await bindingFixture();
  const binder = fixture.binder({
    async stat(candidate) {
      const observed = await fs.stat(candidate);
      return { ...observed, ino: 0, isFile: () => observed.isFile() };
    },
  });
  await assert.rejects(
    binder.preflight({ destinationPath: fixture.projectRoot, threadIds: [TASK_A] }),
    (error) => error instanceof DesktopProjectBindingError &&
      error.code === "state-identity-unavailable",
  );
});

test("binding atomically assigns tasks cleans projectless state and preserves rollout bytes", async () => {
  const fixture = await bindingFixture({
    projectless: [TASK_A, "other-task"],
    projectlessOutputs: { [TASK_A]: "/tmp/output", "other-task": "/tmp/other" },
  });
  const rolloutHash = await hashFile(fixture.rolloutPath);
  const binder = fixture.binder();
  const plan = await binder.preflight({
    destinationPath: fixture.projectRoot,
    threadIds: [TASK_A, TASK_B, TASK_A],
  });
  assert.equal(plan.mode, "ready");
  const result = await binder.bind(plan, [TASK_A, TASK_B]);
  assert.equal(result.status, "bound");
  assert.equal(result.bound, 2);

  const state = JSON.parse(await fs.readFile(fixture.statePath, "utf8"));
  assert.deepEqual(state.unrelated, { keep: true });
  assert.deepEqual(state["projectless-thread-ids"], ["other-task"]);
  assert.deepEqual(state["thread-projectless-output-directories"], {
    "other-task": "/tmp/other",
  });
  for (const threadId of [TASK_A, TASK_B]) {
    assert.deepEqual(state["thread-project-assignments"][threadId], {
      projectKind: "local",
      projectId: "project-a",
      cwd: await fs.realpath(fixture.projectRoot),
      pendingCoreUpdate: false,
    });
  }
  assert.deepEqual(
    JSON.parse(await fs.readFile(result.backupPath, "utf8")),
    fixture.state,
  );
  assert.equal((await fs.stat(result.backupPath)).mode & 0o777, 0o600);
  assert.equal(await hashFile(fixture.rolloutPath), rolloutHash);

  const secondPlan = await binder.preflight({
    destinationPath: fixture.projectRoot,
    threadIds: [TASK_A, TASK_B],
  });
  assert.deepEqual(await binder.bind(secondPlan, [TASK_A, TASK_B]), {
    status: "unchanged",
    attempted: 2,
    bound: 2,
  });
});

test("preflight rejects missing ambiguous malformed and conflicting project state", async () => {
  const cases = [
    {
      code: "project-missing",
      mutate(state) { state["local-projects"] = {}; },
    },
    {
      code: "project-ambiguous",
      mutate(state, root) {
        state["local-projects"]["project-b"] = {
          id: "project-b", name: "Duplicate", rootPaths: [root], createdAt: 1, updatedAt: 1,
        };
      },
    },
    {
      code: "state-malformed",
      mutate(state) { state["local-projects"] = []; },
    },
    {
      code: "state-malformed",
      mutate(state) { state["projectless-thread-ids"] = {}; },
    },
    {
      code: "assignment-conflict",
      mutate(state) {
        state["thread-project-assignments"][TASK_A] = {
          projectKind: "local", projectId: "other-project", pendingCoreUpdate: false,
        };
      },
    },
    {
      code: "state-malformed",
      mutate(state, root) {
        state["thread-project-assignments"][TASK_A] = {
          projectKind: "local",
          projectId: "project-a",
          cwd: root,
          pendingCoreUpdate: false,
          futureField: true,
        };
      },
    },
  ];
  for (const entry of cases) {
    const fixture = await bindingFixture({ mutate: entry.mutate });
    await assert.rejects(
      fixture.binder().preflight({ destinationPath: fixture.projectRoot, threadIds: [TASK_A] }),
      (error) => error instanceof DesktopProjectBindingError && error.code === entry.code,
      entry.code,
    );
  }
});

test("a concurrent state change aborts binding and preserves the newer state", async () => {
  const fixture = await bindingFixture();
  const binder = fixture.binder();
  const plan = await binder.preflight({ destinationPath: fixture.projectRoot, threadIds: [TASK_A] });
  const changed = { ...fixture.state, concurrent: true };
  await fs.writeFile(fixture.statePath, JSON.stringify(changed));
  await assert.rejects(
    binder.bind(plan, [TASK_A]),
    (error) => error instanceof DesktopProjectBindingError && error.code === "state-changed",
  );
  assert.deepEqual(JSON.parse(await fs.readFile(fixture.statePath, "utf8")), changed);
});

test("post-write verification failure restores the exact original state", async () => {
  const fixture = await bindingFixture();
  const original = await fs.readFile(fixture.statePath);
  const binder = fixture.binder({
    async rename(source, destination) {
      await fs.rename(source, destination);
      if (destination === fixture.statePath && source.includes("-state-")) {
        await fs.writeFile(destination, "{}");
      }
    },
  });
  const plan = await binder.preflight({ destinationPath: fixture.projectRoot, threadIds: [TASK_A] });
  await assert.rejects(
    binder.bind(plan, [TASK_A]),
    (error) => error instanceof DesktopProjectBindingError && error.code === "state-malformed",
  );
  assert.deepEqual(await fs.readFile(fixture.statePath), original);
});

test("Windows project paths normalize case separators and trailing slashes", () => {
  assert.equal(
    normalizeDesktopProjectPath("C:/Users/WM/Repo/", "win32"),
    normalizeDesktopProjectPath("c:\\users\\wm\\repo", "win32"),
  );
  assert.equal(normalizeDesktopProjectPath("C:\\", "win32"), "c:\\");
});

test("Windows project matching and custom CODEX_HOME use native path rules", async () => {
  const dependencies = {
    platform: "win32",
    env: { CODEX_HOME: "D:\\CodexHome" },
    homeDir: () => "C:\\Users\\WM",
    realpath: async (candidate) => candidate,
  };
  assert.equal(
    desktopStatePath(dependencies),
    "D:\\CodexHome\\.codex-global-state.json",
  );
  assert.equal(
    await canonicalPath("C:\\Users\\WM\\Repo\\", dependencies),
    "C:\\Users\\WM\\Repo",
  );
  assert.equal(
    await exactlyMatchingProjectId({
      "local-projects": {
        "project-a": {
          id: "project-a",
          rootPaths: ["C:\\Users\\WM\\Repo\\"],
        },
      },
    }, "c:\\users\\wm\\repo", dependencies),
    "project-a",
  );
});

async function bindingFixture(options = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "codex-binding-"));
  const codexHome = path.join(root, "codex-home");
  const projectRoot = path.join(root, "project");
  await fs.mkdir(codexHome);
  await fs.mkdir(projectRoot);
  const statePath = path.join(codexHome, ".codex-global-state.json");
  const rolloutPath = path.join(codexHome, `${TASK_A}.jsonl`);
  const state = {
    "local-projects": {
      "project-a": {
        id: "project-a", name: "Project", rootPaths: [projectRoot], createdAt: 1, updatedAt: 1,
      },
    },
    "thread-project-assignments": {},
    "projectless-thread-ids": options.projectless ?? [],
    "thread-projectless-output-directories": options.projectlessOutputs ?? {},
    unrelated: { keep: true },
  };
  options.mutate?.(state, projectRoot);
  await fs.writeFile(statePath, JSON.stringify(state));
  await fs.writeFile(rolloutPath, '{"type":"session_meta"}\n');
  let randomCounter = 0;
  return {
    root,
    codexHome,
    projectRoot,
    statePath,
    rolloutPath,
    state,
    binder(overrides = {}) {
      return createCodexDesktopProjectBinder({
        dependencies: {
          env: { CODEX_HOME: codexHome },
          inspectDesktop: async () => ({ status: "closed" }),
          now: () => 1234,
          randomId: () => `id-${++randomCounter}`,
          ...overrides,
        },
      });
    },
  };
}

async function hashFile(filePath) {
  return crypto.createHash("sha256").update(await fs.readFile(filePath)).digest("hex");
}
