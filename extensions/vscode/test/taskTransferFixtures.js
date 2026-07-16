function task(threadId, availability = "remote") {
  return {
    threadId,
    title: `Task ${threadId}`,
    updatedAt: "2026-07-15T12:00:00Z",
    estimatedSyncBytes: 1024,
    availability,
    state: availability === "remote" ? "remote_only" : "synced",
    action: availability === "remote" ? "pull" : "none",
  };
}

function project(overrides = {}) {
  return {
    projectKey: overrides.projectKey ?? "git:https://example.com/repo.git",
    projectLabel: overrides.projectLabel ?? "Repo",
    identityKind: overrides.identityKind ?? "git",
    candidateRoots: overrides.candidateRoots ?? [],
    tasks: overrides.tasks ?? [task("remote-task")],
  };
}

function inventory(projects = [], issues = []) {
  return { inventoryVersion: 2, projects, issues };
}

function completed(operation, threadIds) {
  const imported = operation === "import" ? [...threadIds] : [];
  const exported = operation === "export" ? [...threadIds] : [];
  return {
    outcome: "completed",
    counts: {
      discovered: threadIds.length,
      selected: threadIds.length,
      remote: imported.length,
      pulled: imported.length,
      pushed: exported.length,
      unchanged: 0,
      conflicts: 0,
      issues: 0,
    },
    timings_ms: { discovery: 0, planning: 0, pull: 0, push: 0, index: 0, total: 0 },
    threads: [],
    pulled: imported,
    pushed: exported,
    issues: [],
  };
}

function issueResult(code, message) {
  return {
    ...completed("import", []),
    outcome: "issue",
    counts: { ...completed("import", []).counts, selected: 1, issues: 1 },
    issues: [{ code, message, thread_id: "remote-task" }],
  };
}

function statusSummary(overrides = {}) {
  return {
    total: 0,
    synced: 0,
    conflicts: 0,
    missing: 0,
    memoryWarnings: 0,
    localChanges: 0,
    remoteChanges: 0,
    fastForwards: 0,
    issues: 0,
    message: "technical sync status",
    ...overrides,
  };
}

function fakePort(options = {}) {
  let folder = options.folder ?? "";
  const inventories = [...(options.inventoryQueue ?? [options.inventory ?? inventory()])];
  const selections = [...(
    options.selectedThreadIdsQueue ?? [options.selectedThreadIds]
  )];
  const chosenFolders = [...(
    options.chosenTransferFolderQueue ?? [options.chosenTransferFolder]
  )];
  const chosenRoots = [...(
    options.chosenProjectRootQueue ?? [options.chosenProjectRoot]
  )];
  const confirmations = [...(
    options.confirmUnverifiedQueue ?? [options.confirmUnverified]
  )];
  const executionResults = [...(
    options.executionResultQueue ?? [options.executionResult]
  )];
  const reviewResults = [...(
    options.reviewResultQueue ?? [options.reviewResult]
  )];

  return {
    folderWrites: [],
    inventoryRequests: [],
    selectionCalls: [],
    projectRootPrompts: [],
    confirmationPrompts: [],
    executions: [],
    reviews: [],
    notifications: [],
    logs: [],
    statuses: [],
    openedFolders: [],
    menuItems: [],
    readFolder: () => folder,
    async writeFolder(value) {
      this.folderWrites.push(value);
      folder = value ?? "";
    },
    async chooseMenu(items) {
      this.menuItems.push(items);
      return options.menuAction;
    },
    async chooseTransferFolder() {
      return chosenFolders.shift();
    },
    async openFolder(value) {
      if (options.openFolderError) {
        throw options.openFolderError;
      }
      this.openedFolders.push(value);
    },
    workspaceRoots() {
      return options.workspaceRoots ?? ["/workspace"];
    },
    async loadInventory(request) {
      this.inventoryRequests.push(request);
      if (options.inventoryError) {
        throw options.inventoryError;
      }
      return inventories.shift() ?? inventory();
    },
    async chooseTasks(operation, rows, initialThreadIds) {
      this.selectionCalls.push({ operation, rows, initialThreadIds: [...initialThreadIds] });
      return selections.shift();
    },
    async chooseProjectRoot(selectedProject, candidates) {
      this.projectRootPrompts.push({ project: selectedProject, candidates: [...candidates] });
      return chosenRoots.shift();
    },
    async confirmUnverifiedProject(selectedProject, chosenPath) {
      this.confirmationPrompts.push({ project: selectedProject, chosenPath });
      return confirmations.shift() ?? false;
    },
    async execute(operation, request) {
      this.executions.push({ operation, request });
      if (options.executionError) {
        throw options.executionError;
      }
      return executionResults.shift() ?? completed(operation, request.threadIds);
    },
    async review(request) {
      this.reviews.push(request);
      if (options.reviewError) {
        throw options.reviewError;
      }
      return reviewResults.shift() ?? statusSummary({ total: request.threadIds.length });
    },
    notify(kind, message) {
      this.notifications.push([kind, message]);
    },
    log(message) {
      this.logs.push(message);
    },
    setTransientStatus(value) {
      this.statuses.push(value);
    },
  };
}

module.exports = {
  completed,
  fakePort,
  inventory,
  issueResult,
  project,
  statusSummary,
  task,
};
