const assert = require("node:assert/strict");
const test = require("node:test");

const {
  eligibleTransferProjects,
  eligibleTransferTasks,
} = require("../out/taskTransferContract");

const tasks = [
  { thread_id: "local", availability: "local" },
  { thread_id: "remote", availability: "remote" },
  { thread_id: "both", availability: "both" },
];

test("Task Transfer eligibility preserves direction and starts without selection state", () => {
  assert.deepEqual(eligibleTransferTasks(tasks, "export").map((task) => task.thread_id), ["local", "both"]);
  assert.deepEqual(eligibleTransferTasks(tasks, "import").map((task) => task.thread_id), ["remote", "both"]);
  assert.deepEqual(eligibleTransferTasks(tasks, "status").map((task) => task.thread_id), ["local", "remote", "both"]);
  assert.ok(tasks.every((task) => !("picked" in task)));
});

test("Task Transfer exposes only projects with tasks eligible for the chosen operation", () => {
  const inventory = {
    projects: [
      { project_key: "one", project_label: "One", tasks: [tasks[0]] },
      { project_key: "two", project_label: "Two", tasks: [tasks[1]] },
    ],
  };
  assert.deepEqual(
    eligibleTransferProjects(inventory, "export").map((entry) => entry.project.project_key),
    ["one"],
  );
  assert.deepEqual(
    eligibleTransferProjects(inventory, "import").map((entry) => entry.project.project_key),
    ["two"],
  );
});
