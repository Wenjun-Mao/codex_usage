# Exact Task Sync Selection Design

Date: 2026-07-14

Status: Approved

## Goal

Replace the current project-or-conversation sync selector with one project-grouped task picker. Users choose exact Codex tasks, and every chosen task synchronizes its complete JSONL through the existing version-2 flat store.

New tasks remain excluded until the user explicitly selects them.

## Terminology Contract

Codex calls each sidebar entry under a project a **task**. The underlying app-server, deep-link, CLI, and local-storage identity is a technical **thread id**. The official desktop command reference makes the same distinction: a `codex://threads/<id>` link opens a local task, and `<id>` is its technical thread id.

Reference: [ChatGPT desktop app commands](https://learn.chatgpt.com/docs/reference/commands)

Use these terms consistently:

- User-facing extension UI and documentation: task, tasks, Select Tasks, Change Tasks.
- Python, TypeScript, JSON, and CLI contracts: `thread_id`, `threadIds`, and `--thread-id`.
- Durable remote data: one byte-preserved JSONL per selected technical thread id.

Do not expose conversation or thread as the name of a selectable sidebar item. A task is the user-facing object; its thread id is an implementation detail.

## Root Cause Note

### What Failed

Sync setup asks users to choose projects and then choose conversations, including a dynamic "all conversations in selected projects" mode. This does not match the Codex product hierarchy, where projects contain named tasks. It also prevents a user from seeing a remote-only task during setup on a machine where that task has not yet been pulled.

### Why It Failed

The selection contract mixes two incompatible models:

1. project keys dynamically include every matching current and future thread;
2. explicit thread ids select an exact set.

The extension stores a `conversationMode` to switch between them and uses a local-only `threads` command for its second picker. User-facing labels call technical thread records conversations even though Codex presents them as tasks.

### Evidence

- `SyncSettings` currently stores `projectKeys`, `conversationMode`, and `threadIds`.
- The picker offers "All conversations in selected projects" and otherwise stores exact thread ids.
- `resolve_selected_thread_ids` expands project keys during every run, so future matching tasks join automatically.
- The existing picker inventory comes only from local active sessions.
- Current Codex documentation calls sidebar work items tasks while describing their ids as technical thread ids.

### Correct Fix Layer

This is a selection and inventory contract problem, not a wording-only issue. The durable fix is one combined local-and-remote inventory, one exact task-selection model, and one user-facing terminology boundary. Relabeling the current project-wide mode would preserve automatic future inclusion and remote-only discovery failures.

## Decision Summary

1. Add one read-only Python sync inventory command that combines local and remote task metadata.
2. Replace project and conversation setup steps with one project-grouped task picker.
3. Persist only exact technical thread ids as sync selectors.
4. Treat project rows as select-all and deselect-all shortcuts for the tasks currently shown under that project.
5. Exclude tasks created after setup until the user selects them.
6. Make the extension selection-state change intentionally breaking; do not migrate old selectors.
7. Keep the version-2 remote layout, planner, transfer, and conflict contracts unchanged.

## Combined Inventory Contract

### CLI Surface

Add this read-only command:

```text
codex-usage sync inventory --sync-dir <path> --json
```

It loads active local sessions once and the selected remote sync folder once. It does not acquire the mutation lock, copy task data, update local base state, or write the remote index.

The conceptual JSON result is:

```json
{
  "inventory_version": 1,
  "projects": [
    {
      "project_key": "<canonical-key>",
      "project_label": "persona_generators",
      "tasks": [
        {
          "thread_id": "<technical-thread-id>",
          "title": "Persona - just_talk",
          "updated_at": "2026-07-14T12:00:00Z",
          "estimated_sync_bytes": 12345,
          "availability": "both"
        }
      ]
    }
  ],
  "issues": []
}
```

Allowed availability values are:

- `local`: task exists only on this device;
- `remote`: task exists only in the sync folder;
- `both`: task exists in both inventories.

Project grouping uses canonical project identity rather than display labels. Projects and tasks use deterministic ordering: projects by display label and canonical key, tasks by most recent update first and thread id as the final tie-breaker.

### Merge Rules

Merge local and remote records by exact thread id.

- When a local record exists, its title, project identity, update time, and size drive the picker display.
- Remote metadata supplies remote-only tasks.
- A task present on both sides has `availability: "both"`.
- Duplicate titles are allowed because the thread id remains authoritative. Picker details include enough identity and availability information to distinguish them.
- Existing in-memory remote reconciliation may reconstruct effective catalog metadata when identity can be established safely, but inventory never persists that repair.

The command uses the existing remote-store validation and path guards. A legacy layout, malformed index, unsafe path, or unreadable folder is a blocking structural failure: the command exits unsuccessfully and the extension does not open or save the picker.

The `issues` array is reserved for non-blocking per-file diagnostics where known entries remain trustworthy but another remote artifact cannot be identified safely. Such an artifact is omitted from the selectable inventory, left untouched, and reported to the user. No issue path may invent a title, project, or thread id.

## One-Step Picker

### Layout

Sync setup chooses or keeps the sync folder, loads the combined inventory with one child process, and opens one multi-select Quick Pick.

Each project has a selectable parent row followed by its task rows. The parent row is a convenience control, not a persisted selector.

Example:

```text
persona_generators                         2 tasks
  Persona - just_talk                     Both
  persona - execution                     This device

mafinance                                  1 task
  mafinance                                Sync folder
```

### Selection Behavior

- Selecting a project row selects every task currently listed under that project.
- Deselecting a selected project row deselects every current child task.
- Selecting or deselecting child tasks creates an exact partial selection.
- A project row appears selected only when every current child task is selected.
- Project toggles operate on every child in the inventory snapshot, even when Quick Pick text filtering hides some children.
- No tasks are globally preselected on a breaking first setup.
- Reopening the picker restores every valid selection written under the new schema.
- Canceling leaves the prior selection untouched.
- Accepting no tasks keeps the picker open and shows a clear validation message.

Selecting a project is therefore one-click convenience for all current tasks, not a subscription to future project activity.

### Unavailable Selected Tasks

If a stored thread id is absent from both the current local and remote inventories, show it in an **Unavailable selected tasks** group. Keep it selected until the user explicitly deselects it.

This prevents a temporarily unavailable folder, stale cloud mount, or local storage change from silently erasing configuration. The unavailable row may display the technical id when no trusted title metadata is available.

## Persisted Selection Contract

Add a dedicated sync-selection schema version. The new contract is valid only when that value equals `2`.

Persist:

- the selected sync folder;
- `syncSelectionVersion = 2`;
- exact selected technical thread ids;
- existing enabled, automatic pull, and automatic push preferences.

Remove sync-specific project keys and `conversationMode` from the active settings model. The dashboard's independent project filter remains unchanged.

When the selection version is missing or not `2`:

- ignore all legacy sync project and thread selectors;
- do not run manual or automatic sync;
- show **Setup required**;
- preserve the sync folder, enabled state, automatic-sync preferences, local files, remote JSONLs, and remote index;
- require the user to open setup and accept a new exact task selection.

Do not add a one-time migration shim. Legacy state may be removed after the new selection is accepted, but it must never be interpreted as a new-schema selection.

## Sync Execution Contract

`sync run` and `sync status` accept explicit repeatable `--thread-id` selectors only. Remove `--project-key` from the sync subcommands. The separate top-level `threads --project-key` filtering command remains available for usage and diagnostic workflows.

The extension passes the stored thread ids directly to status, manual sync, and automatic sync. It launches no preliminary inventory command during routine synchronization. The inventory command is used only while configuring task selection.

Existing version-2 behavior remains unchanged for selected ids:

- one process and one local discovery inventory per run;
- full conflict preflight;
- pulls before pushes;
- byte-prefix-aware fast forwards;
- one byte-preserved JSONL per task;
- no deletion caused by deselection;
- no synchronization of archived local tasks in this slice.

Adding a new local task under a selected task's project does not affect the next plan because the new thread id is not selected.

## UI Copy

Replace user-facing sync terminology throughout commands, status controls, progress, errors, and documentation:

- Configure Sync -> setup includes Select Tasks;
- Change Projects and Change Conversations -> Change Tasks;
- Select Conversations -> Select Tasks;
- N conversations selected -> N tasks selected;
- Pull selected conversations -> Pull selected tasks;
- conversation-specific errors -> task-specific errors when referring to a selectable Codex item.

Technical diagnostics may include `thread_id`. Storage documentation may explain that a selected task is stored under its technical thread id, but should not rename the user-facing object.

## Failure Handling

- An empty remote folder returns local tasks normally.
- Remote-only projects and tasks remain selectable and can be pulled.
- Inventory failures do not mutate settings or sync data.
- A selected id missing from both inventories remains visible as unavailable rather than being discarded.
- Invalid legacy selection state never starts automatic sync.
- Routine sync with no valid selected ids reports setup required before spawning the CLI.
- Changing or canceling task setup cannot delete remote JSONLs or index entries.

## Module Boundaries

Keep project identity, local and remote inventory merging, and remote validation in Python. The TypeScript extension owns VS Code picker interaction, selected-row state, and process orchestration; it must not parse `sync-index.json` directly.

Place strict inventory JSON parsing in a focused TypeScript module rather than growing `extension.ts` or `core.ts` with another protocol. Keep picker state transitions in independently testable pure functions where practical.

The Python inventory model and command handler should live in focused sync modules and reuse the existing `LocalInventory`, `RemoteStore`, and project-identity contracts.

## Documentation And ADRs

ADR 0012 records the exact-task selection and terminology boundary. It supersedes the selection portions of ADR 0007 and ADR 0011, but does not change their bring-your-own-folder, flat-storage, one-process, or conflict decisions.

Update:

- repository README;
- extension README;
- root and extension changelogs;
- ADR index;
- CLI examples that currently show project-key sync selection.

Document that this release intentionally requires sync selection to be configured again. No remote cleanup or republishing is required solely because of this settings break.

## Testing And Acceptance

### Python

- Merge local-only, remote-only, and shared task records by thread id.
- Group tasks by canonical project identity with deterministic ordering.
- Prefer local display metadata when a task exists on both sides.
- Return local tasks for an empty remote folder.
- Reject malformed indexes, legacy layouts, unsafe paths, and unreadable folders without writes.
- Prove inventory does not change remote or local sync state.
- Accept only explicit thread ids in sync status and run.
- Pull a selected remote-only task successfully.
- Leave unselected and newly created tasks untouched.

### VS Code Extension

- Strictly parse valid inventory payloads and reject malformed fields.
- Render project parents and task children from one inventory snapshot.
- Select and deselect all current project children through the parent row.
- Handle partial project selections and filtered views deterministically.
- Restore new-schema selections on reopen.
- Preserve unavailable selected ids until explicit deselection.
- Reject empty acceptance and preserve settings on cancel or inventory failure.
- Treat missing or obsolete selection versions as setup required.
- Build status and run arguments from thread ids only.
- Use task terminology in every user-facing sync label.

### End To End And Packaging

- Select two tasks under one project and synchronize both.
- Create a third task under that project and prove it remains excluded.
- Configure a second machine from remote-only inventory and pull a selected task.
- Keep one inventory subprocess for setup and one subprocess for each routine sync action.
- Exercise inventory and exact-id sync in packaged Windows x64 and macOS arm64 smoke tests.
- Run the full Python and extension test suites after each major implementation slice.

## Out Of Scope

- Automatically selecting future tasks in a chosen project.
- Selecting individual turns, messages, or portions of a task JSONL.
- Changing the version-2 remote layout or conflict planner.
- Syncing archived local tasks.
- Migrating legacy selection settings.
- Deleting remote data when a task is deselected.
- Renaming internal thread-id fields solely to match UI terminology.
