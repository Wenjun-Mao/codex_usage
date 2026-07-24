const assert = require("node:assert/strict");
const test = require("node:test");

const {
  requireSelectedTransferProject,
  TransferProjectScopeError,
} = require("../out/taskTransferProjectScope");
const { inventory, project, task } = require("./taskTransferFixtures");

const source = inventory([
  project({
    projectKey: "repo-a",
    projectLabel: "Repo A",
    tasks: [
      task("thread-1", "remote"),
      task("thread-2", "remote"),
      task("thread-4", "both"),
    ],
  }),
  project({
    projectKey: "repo-b",
    projectLabel: "Repo B",
    tasks: [task("thread-3", "remote")],
  }),
]);

test("returns the selected project and a valid import subset", () => {
  assert.deepEqual(
    requireSelectedTransferProject(source, "import", {
      projectKey: "repo-a",
      threadIds: ["thread-2"],
    }),
    {
      project: source.projects[0],
      projectKey: "repo-a",
      projectLabel: "Repo A",
      threadIds: ["thread-2"],
    },
  );
});

test("rejects a selected task outside the declared project", () => {
  assert.throws(
    () => requireSelectedTransferProject(source, "import", {
      projectKey: "repo-a",
      threadIds: ["thread-3"],
    }),
    (error) =>
      error instanceof TransferProjectScopeError &&
      /one project at a time/i.test(error.message),
  );
});

test("rejects selected task ids from two projects", () => {
  assert.throws(
    () => requireSelectedTransferProject(source, "import", {
      projectKey: "repo-a",
      threadIds: ["thread-2", "thread-3"],
    }),
    /one project at a time/i,
  );
});

test("rejects a missing picker project", () => {
  assert.throws(
    () => requireSelectedTransferProject(source, "import", {
      threadIds: ["thread-2"],
    }),
    /one project at a time/i,
  );
});

test("rejects an empty selected task subset", () => {
  assert.throws(
    () => requireSelectedTransferProject(source, "import", {
      projectKey: "repo-a",
      threadIds: [],
    }),
    /one project at a time/i,
  );
});

test("filters by operation and deduplicates selected ids in picker order", () => {
  const localOnly = inventory([
    project({
      projectKey: "repo-a",
      projectLabel: "Repo A",
      tasks: [task("thread-1", "local")],
    }),
  ]);
  assert.throws(
    () => requireSelectedTransferProject(localOnly, "import", {
      projectKey: "repo-a",
      threadIds: ["thread-1"],
    }),
    /one project at a time/i,
  );
  assert.deepEqual(
    requireSelectedTransferProject(source, "import", {
      projectKey: "repo-a",
      threadIds: ["thread-4", "thread-2", "thread-4"],
    }).threadIds,
    ["thread-4", "thread-2"],
  );
});
