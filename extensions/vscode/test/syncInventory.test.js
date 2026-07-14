const assert = require("node:assert/strict");
const test = require("node:test");

const { buildSyncInventoryArgs, parseSyncInventory } = require("../out/syncInventory");

function inventoryTask(overrides = {}) {
  return {
    thread_id: "thread-1",
    title: "Persona - execution",
    updated_at: "2026-07-14T12:00:00Z",
    estimated_sync_bytes: 2048,
    availability: "remote",
    ...overrides,
  };
}

function inventoryProject(overrides = {}) {
  return {
    project_key: "repo-a",
    project_label: "Repo A",
    tasks: [inventoryTask()],
    ...overrides,
  };
}

function inventoryIssue(overrides = {}) {
  return {
    code: "unreadable_session",
    message: "Could not read the local session.",
    thread_id: "thread-2",
    ...overrides,
  };
}

function inventory(overrides = {}) {
  return {
    inventory_version: 1,
    projects: [inventoryProject()],
    issues: [],
    ...overrides,
  };
}

function withoutField(record, field) {
  const copy = { ...record };
  delete copy[field];
  return copy;
}

test("inventory args use one read-only command", () => {
  assert.deepEqual(buildSyncInventoryArgs({ syncDir: " D:/Sync ", autoTransitions: false }), [
    "sync",
    "inventory",
    "--json",
    "--sync-dir",
    "D:/Sync",
    "--no-auto-transitions",
  ]);
  assert.deepEqual(buildSyncInventoryArgs({ syncDir: "   ", autoTransitions: true }), [
    "sync",
    "inventory",
    "--json",
  ]);
});

test("inventory parser preserves project tasks and availability", () => {
  const parsed = parseSyncInventory(JSON.stringify(inventory({ issues: [inventoryIssue()] })));

  assert.deepEqual(parsed, {
    inventoryVersion: 1,
    projects: [
      {
        projectKey: "repo-a",
        projectLabel: "Repo A",
        tasks: [
          {
            threadId: "thread-1",
            title: "Persona - execution",
            updatedAt: "2026-07-14T12:00:00Z",
            estimatedSyncBytes: 2048,
            availability: "remote",
          },
        ],
      },
    ],
    issues: [
      {
        code: "unreadable_session",
        message: "Could not read the local session.",
        threadId: "thread-2",
      },
    ],
  });
  assert.equal(parsed.projects[0].tasks[0].availability, "remote");
});

test("inventory parser accepts every availability and the largest safe byte count", () => {
  const payload = inventory({
    projects: [
      inventoryProject({
        tasks: [
          inventoryTask({ thread_id: "local", availability: "local", estimated_sync_bytes: 0 }),
          inventoryTask({ thread_id: "remote", availability: "remote" }),
          inventoryTask({
            thread_id: "both",
            availability: "both",
            estimated_sync_bytes: Number.MAX_SAFE_INTEGER,
          }),
        ],
      }),
    ],
  });

  const parsed = parseSyncInventory(JSON.stringify(payload));

  assert.deepEqual(
    parsed.projects[0].tasks.map((task) => task.availability),
    ["local", "remote", "both"],
  );
  assert.equal(parsed.projects[0].tasks[2].estimatedSyncBytes, Number.MAX_SAFE_INTEGER);
});

test("inventory parser rejects contract violations at the failing field path", () => {
  const malformedCases = [
    {
      name: "malformed JSON",
      json: "{",
      path: "json",
    },
    {
      name: "extra top-level key",
      payload: inventory({ unexpected: true }),
      path: "unexpected",
    },
    {
      name: "missing top-level field",
      payload: withoutField(inventory(), "projects"),
      path: "projects",
    },
    {
      name: "unsupported inventory version",
      payload: inventory({ inventory_version: 2 }),
      path: "inventory_version",
    },
    {
      name: "extra project key",
      payload: inventory({ projects: [inventoryProject({ unexpected: true })] }),
      path: "projects[0].unexpected",
    },
    {
      name: "missing project field",
      payload: inventory({ projects: [withoutField(inventoryProject(), "project_label")] }),
      path: "projects[0].project_label",
    },
    {
      name: "duplicate project key",
      payload: inventory({
        projects: [inventoryProject(), inventoryProject({ project_label: "Duplicate" })],
      }),
      path: "projects[1].project_key",
    },
    {
      name: "extra task key",
      payload: inventory({
        projects: [inventoryProject({ tasks: [inventoryTask({ unexpected: true })] })],
      }),
      path: "projects[0].tasks[0].unexpected",
    },
    {
      name: "missing task field",
      payload: inventory({
        projects: [inventoryProject({ tasks: [withoutField(inventoryTask(), "title")] })],
      }),
      path: "projects[0].tasks[0].title",
    },
    {
      name: "duplicate thread id across projects",
      payload: inventory({
        projects: [inventoryProject(), inventoryProject({ project_key: "repo-b", project_label: "Repo B" })],
      }),
      path: "projects[1].tasks[0].thread_id",
    },
    {
      name: "invalid availability",
      payload: inventory({
        projects: [inventoryProject({ tasks: [inventoryTask({ availability: "missing" })] })],
      }),
      path: "projects[0].tasks[0].availability",
    },
    {
      name: "unsafe byte count",
      payload: inventory({
        projects: [
          inventoryProject({ tasks: [inventoryTask({ estimated_sync_bytes: Number.MAX_SAFE_INTEGER + 1 })] }),
        ],
      }),
      path: "projects[0].tasks[0].estimated_sync_bytes",
    },
    {
      name: "negative byte count",
      payload: inventory({
        projects: [inventoryProject({ tasks: [inventoryTask({ estimated_sync_bytes: -1 })] })],
      }),
      path: "projects[0].tasks[0].estimated_sync_bytes",
    },
    {
      name: "missing issue field",
      payload: inventory({ issues: [withoutField(inventoryIssue(), "message")] }),
      path: "issues[0].message",
    },
    {
      name: "extra issue key",
      payload: inventory({ issues: [inventoryIssue({ detail: "internal" })] }),
      path: "issues[0].detail",
    },
    {
      name: "malformed issue field",
      payload: inventory({ issues: [inventoryIssue({ thread_id: null })] }),
      path: "issues[0].thread_id",
    },
  ];

  for (const { name, json, payload, path } of malformedCases) {
    assert.throws(
      () => parseSyncInventory(json ?? JSON.stringify(payload)),
      (error) => {
        assert.match(error.message, /^Invalid sync inventory: /, name);
        assert.match(error.message, new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), name);
        return true;
      },
      name,
    );
  }
});
