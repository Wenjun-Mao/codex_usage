# Task Transfer UX And Storage V3 Design

Date: 2026-07-15

Status: Approved

## Goal

Optimize the VS Code extension for deliberate Codex task transfer between
computers rather than presenting it as an ongoing synchronization service.

The next release makes token-usage reporting independent from Task Transfer,
replaces persistent task selection with fresh per-operation selection, renames the
portable task directory from `conversations/` to `tasks/`, and removes the legacy
enabled and paused state completely.

The primary workflow is:

1. Export selected active tasks on the source computer.
2. Allow the user's filesystem provider to copy the transfer folder.
3. Import selected tasks on the destination computer.
4. Restart Codex so it discovers the imported task files.

This supports same-OS and cross-OS transfer, including large tasks that Codex's
built-in handoff cannot complete.

## Root Cause Note

### What Failed

The extension currently presents a manual transfer feature as **Sync**. The status
bar can show `Codex Usage: 7d Sync: Setup required`, even though token reporting
does not depend on transfer configuration. A no-op command reports `Pulled 0
tasks`, which is numerically correct but does not explain whether the folder is
empty, the tasks are current, or the opposite direction is required.

The extension also remembers a task set and exposes **Pause Sync**, **Resume
Sync**, and `codexUsage.sync.enabled`. Those controls imply a continuously mirrored
relationship even though transfers only run after an explicit command.

The portable folder compounds the terminology mismatch by storing Codex tasks
under `conversations/`.

### Why It Failed

The presentation and persistence models still inherit concepts from the former
automatic-sync design:

- usage status and transfer setup share one persistent status label;
- enabled and paused state remain after all automatic triggers were removed;
- Pull and Push describe storage mechanics instead of the user's source and
  destination intent;
- persistent selection treats a transfer as a lasting relationship;
- current UI and documentation mix tasks, threads, and conversations;
- the version-2 portable layout exposes `conversations/` to users.

### Evidence

- `syncStatusBadge` and `syncControlLabel` render setup-required copy next to token
  usage.
- `SyncSettings`, `SyncSetupState`, and the setup transaction persist an enabled
  boolean and exact selected task ids.
- the Sync menu exposes Pause, Resume, Change Tasks, and selected-task counts.
- completion notifications can report only a zero transfer count.
- task pickers leak `Thread ID`, `local`, and `remote` vocabulary.
- ADR 0013 already prohibits activation, focus, timer, and file-watcher
  transfers, so Pause and Resume do not control a background process.
- the remote index stores paths such as `conversations/<task-id>.jsonl`.

### Correct Fix Layer

This is a product-model and storage-contract mismatch, not only a wording defect.
The durable fix is to model the feature as three explicit Task Transfer operations,
persist only the transfer folder, and update the user-visible portable layout.
Relabeling the existing setup and pause controls would preserve the invalid state
model.

## Product Contract

Codex Usage token reporting is always available. It never requires a transfer
folder, task selection, or Task Transfer operation.

Task Transfer is optional, directional, manual, and non-destructive:

- **Export Tasks** copies selected active tasks from this computer to the transfer
  folder.
- **Import Tasks** copies selected tasks from the transfer folder to this computer.
- **Review Transfer Status** inspects task state without copying files.
- no operation runs on activation, focus, a timer, a file watcher, or an enabled
  setting.
- importing a task does not remove it from the transfer folder.
- forgetting the transfer folder does not delete anything from that folder or
  from Codex.

The extension remembers only the transfer-folder path. Each operation starts with
a fresh selection and stores no selected project or task ids.

## Primary Usage Scenario

The README and Marketplace description lead with deliberate task transfer between
computers. They must not describe the feature as maintaining two mirrored Codex
installations.

The documented workflow is:

1. On the source computer, choose **Export Tasks**.
2. Choose the active projects and tasks to transfer.
3. Wait for OneDrive, Dropbox, iCloud Drive, Syncthing, a network drive, or another
   filesystem provider to finish copying the transfer folder.
4. On the destination computer, choose **Import Tasks**.
5. Choose the tasks to import.
6. Restart Codex to make imported tasks visible.

The usage scenario explicitly calls out large Codex tasks for which built-in
handoff is unavailable or fails because of task size. Token reporting remains the
extension's independent core capability.

## Remembered Folder And Lazy Setup

There is no setup-required state.

The dashboard always exposes **Task Transfer**. If Import, Export, or Review is
invoked without a remembered folder, the extension opens a folder picker and
remembers the chosen path before continuing. Cancelling the folder picker ends the
command silently.

The Task Transfer menu exposes:

- **Import Tasks**;
- **Export Tasks**;
- **Review Transfer Status**;
- **Choose Transfer Folder** when no path is remembered;
- **Change Transfer Folder** when a path is remembered;
- **Open Transfer Folder** when a path is remembered;
- **Forget Transfer Folder** when a path is remembered.

Remove Setup, Clear Setup, Pause, Resume, Change Tasks, and every persistent
selected-task count. Forgetting the folder clears only the saved path.

## Fresh Per-Operation Selection

Every operation loads a current inventory and opens the same combined project and
task picker with operation-specific filtering:

- Import lists tasks that exist in the transfer folder.
- Export lists active tasks that exist on this computer.
- Review lists the union of tasks known on either side.

Tasks are grouped beneath their project. Selecting a project selects every visible
task beneath it; users may then adjust individual tasks. No project or task is
preselected, and the result is not persisted after the command finishes.

Archived Codex tasks remain excluded from export and discovery. Historical usage
accounting for archived tasks is unchanged.

Each task row uses user-facing state and availability wording:

- `Ready to import`;
- `Ready to export`;
- `Up to date`;
- `Conflict`;
- `Missing`;
- `On this computer`;
- `In transfer folder`;
- `On both`.

Technical thread ids may appear as **Task ID** when disambiguation is needed. The
picker never labels a Codex sidebar item as a conversation or thread.

## Directional Safety Contract

Import and Export preflight every selected task before copying anything. A command
is all-or-nothing for its selected set.

Up-to-date tasks are harmless no-ops. The following conditions block the entire
operation:

- a true three-way conflict;
- a selected source file disappearing or changing during preflight;
- malformed or unsafe transfer-folder structure;
- a selected task requiring the opposite direction.

Export never overwrites a newer transfer-folder copy. It tells the user to import
that task first. Import never overwrites a newer copy on this computer. It tells
the user to export that task first.

The planner, hashes, paired baselines, optimistic remote snapshots, and path-safety
checks remain authoritative. Presentation code cannot weaken or bypass them.

## Result And Error Copy

Results describe state rather than exposing a raw zero count.

### Empty Sources

```text
No tasks are available to import from this transfer folder.
No active Codex tasks are available to export from this computer.
```

### No Changes Needed

```text
No changes were needed. The selected task is up to date.
No changes were needed. All 2 selected tasks are up to date.
```

### Successful Transfer

```text
Imported 1 task. Restart Codex to see it.
Imported 2 tasks. Restart Codex to see them.
Exported 1 task to the transfer folder.
Exported 2 tasks to the transfer folder.
```

### Blocked Direction

```text
Export was blocked because 1 selected task is newer in the transfer folder. Import it first.
Import was blocked because 2 selected tasks are newer on this computer. Export them first.
```

Conflict and malformed-folder notifications give a concise explanation and state
that no tasks were copied. Full technical details go to the Codex Usage output
channel. Cancelling any picker is silent.

A successful version-2 migration is transparent. Migration warnings appear only
when the folder cannot be converted safely.

## Status Bar And Dashboard

The persistent status bar is usage-only:

```text
Codex Usage: 7d
Codex Usage: 7d (2)
```

It must not show setup-required, selected-task, enabled, paused, or idle transfer
state. During a command it may append transient progress or failure text:

```text
Codex Usage: 7d | Checking tasks
Codex Usage: 7d | Importing tasks
Codex Usage: 7d | Exporting tasks
Codex Usage: 7d | Task transfer conflict
Codex Usage: 7d | Task transfer issue
```

After the command completes and its notification is shown, the status returns to
usage-only.

The dashboard action is always:

```text
Task Transfer ▾
```

The usage tooltip contains no transfer-configuration warning.

## User-Facing And Technical Terminology

Current user-facing extension UI and current-behavior documentation use:

- Task Transfer;
- Import Tasks, Export Tasks, and Review Transfer Status;
- task, tasks, Task ID, and Task IDs;
- this computer;
- transfer folder;
- On this computer, In transfer folder, and On both;
- estimated transfer size.

Technical contracts retain:

- `thread_id` and `threadIds`;
- `--thread-id`;
- the `threads` inventory command;
- `sync pull`, `sync push`, and `sync status`;
- `sync-index.json` and its `threads` map;
- protocol values `local`, `remote`, and `both`;
- hashes, baselines, and low-level diagnostics.

The portable task directory is the deliberate exception: it changes from
`conversations/` to `tasks/` because users can inspect this folder directly.

Historical changelog bullets and archived design records may retain vocabulary
that accurately describes an earlier release. Current README and Marketplace
copy must follow this terminology contract.

## Portable Transfer Format Version 3

The canonical remote layout becomes:

```text
<transfer-folder>/
  sync-index.json
  tasks/
    <portable-task-filename>.jsonl
```

Each task remains one byte-identical source JSONL. The transfer engine does not
split, combine, normalize, summarize, or rewrite its event stream.

`sync-index.json` remains the catalog filename and retains its technical `threads`
map. Every indexed file path must be a direct child of `tasks/`. The remote format
version changes from 2 to 3.

Remote transfer format and local paired-baseline state are separate contracts.
Introduce separate version constants:

- remote transfer format version `3`;
- unchanged local baseline-state version `2`.

The existing shared constant must no longer invalidate unchanged local baselines
when only the portable layout changes.

## Version-2 Folder Migration

The new release accepts a valid version-2 folder and migrates it before Import,
Export, or Review. Migration runs through the Python storage layer, under the
existing local transaction lock and optimistic snapshot guards.

Migration follows this commit order:

1. Load, reconcile, and fully validate the version-2 index and every referenced
   `conversations/*.jsonl` file without mutation.
2. Create `tasks/` if needed.
3. Copy each verified source JSONL atomically into `tasks/` and verify its bytes,
   hash, size, and task identity.
4. Reuse a matching staged file when resuming an interrupted migration.
5. Stop without overwriting when a staged destination differs from its verified
   source.
6. Build a version-3 index whose entries point to `tasks/...`.
7. Atomically replace `sync-index.json` last.
8. Remove `conversations/` only after the version-3 index is durable and every
   legacy file is represented by an identical version-3 task file.

A failure before index replacement leaves the version-2 index and
`conversations/` authoritative. A later command can resume from matching staged
files. A failure after index replacement leaves version 3 authoritative; a
matching legacy directory is safe to clean up on a later command.

If both directories contain conflicting bytes or unrepresented files, migration
stops and preserves both. The extension reports the conflicting paths and copies
no selected tasks.

An older extension presented with format version 3 must reject it as unsupported
rather than mutating it.

## Upgrade Migration Of Extension State

On activation, preserve the remembered folder and remove obsolete state:

- remove explicit `codexUsage.sync.enabled` values from global, workspace, and
  workspace-folder configuration scopes;
- remove persisted exact task ids;
- remove the persisted selection-schema version;
- remove Pause and Resume runtime state.

Cleanup is idempotent. Failure to delete an obsolete setting is logged, but the
obsolete value is ignored and cannot block activation, token reporting, or Task
Transfer.

The existing saved-folder key remains stable so users do not have to choose the
folder again. All task files, the remote catalog, and local paired baselines are
preserved. No migration notification is shown when nothing is lost.

Because only one folder value remains, remove the multi-value setup transaction
rather than preserving rollback machinery for state that no longer exists.

## Architecture And Ownership

### Python Transfer Engine

Python remains authoritative for:

- local and transfer-folder inventory;
- task identity and project resolution;
- status planning and all-or-nothing preflight;
- conflict and opposite-direction detection;
- atomic file copying and optimistic concurrency checks;
- version-2 to version-3 migration.

Add a focused migration module instead of adding another responsibility to the
storage module. Keep the planner's technical local/remote model and existing CLI
commands as implementation details.

### Extension Orchestration

Add a focused Task Transfer orchestration module that owns:

- lazy folder selection and persistence;
- operation-specific inventory requests;
- fresh combined project/task selection;
- invoking the bundled CLI with selected technical thread ids;
- progress and completion notifications.

Add a pure presentation module that owns:

- Task Transfer menu items;
- picker labels and task states;
- transient status text;
- result and error-message formatting.

Move existing transfer helpers out of `core.ts` and `extension.ts`, which are
already above the repository's 500-line review threshold. Command registration in
`extension.ts` delegates to the orchestration module. Pure presentation behavior
must not depend on the VS Code API.

Existing extension command ids remain stable where their hidden names use pull,
push, status, or sync. Their displayed titles and descriptions use Import, Export,
Review Transfer Status, and Task Transfer.

## Documentation And Changelog Policy

The root README and extension README must:

- state that token-usage reporting works without Task Transfer;
- lead Task Transfer documentation with the source-to-destination usage scenario;
- include the Export, provider-convergence, Import, and Codex-restart sequence;
- call out large tasks that cannot be moved with Codex's built-in handoff;
- state that imported files remain in the transfer folder;
- state that every operation uses a fresh task selection;
- avoid claiming ongoing, automatic, or bidirectional synchronization;
- place internal `sync` CLI commands in a clearly technical section.

Update Marketplace copy, command lists, screenshots or literal status examples,
and troubleshooting instructions to match the same contract.

Both changelogs gain an undated top section:

```text
## Unreleased
```

Released headings use ISO dates while preserving descriptive titles:

```text
## 0.1.35 - 2026-07-14 - Manual Cross-Platform Task Transfer
```

Backfill each existing heading with the date of the commit that first introduced
that release heading. The root changelog is canonical when an extension entry was
copied later. Matching versions in both files use identical dates. No date is
guessed.

Future notable changes start under `Unreleased`. Release preparation moves those
changes into a version heading with the actual release date.

## Error Handling

- A missing remembered folder opens the folder picker instead of reporting setup
  failure.
- A missing or offline remembered folder produces an actionable folder error and
  performs no write.
- Cancelling a folder or task picker is not an error.
- An empty import or export source gets a state-specific no-tasks message.
- A blocked preflight copies none of the selected tasks.
- A zero-transfer result is not called a failure and is not called up to date when
  an opposite-direction blocker exists.
- Migration validates before mutation and commits the version-3 index last.
- Symlink, path traversal, identity mismatch, malformed index, and concurrent
  change protections remain mandatory.
- Task Transfer never patches Codex SQLite. Restart guidance is presentation, not
  a private-database mutation.

## Testing And Guardrails

Use test-driven implementation.

### Python Tests

Add tests for:

- complete version-2 to version-3 migration;
- byte, hash, size, identity, catalog, and baseline preservation;
- recovery from interruption before version-3 index commit;
- cleanup after interruption following index commit;
- matching and conflicting dual-directory states;
- refusal to overwrite conflicting staged files;
- malformed layouts, symlinks, path traversal, and concurrent changes;
- v3 direct-child `tasks/` validation;
- all-or-nothing Import and Export preflight;
- opposite-direction, conflict, missing, and up-to-date selected sets.

### Extension Tests

Add pure and integration tests for:

- lazy folder selection, persistence, cancellation, change, open, and forget;
- fresh unselected task pickers for every operation;
- project select-all and individual task adjustment;
- Import, Export, and Review inventory filtering;
- all user-facing availability and transfer-state labels;
- empty, up-to-date, successful, opposite-direction, conflict, and issue messages;
- restart guidance only after at least one imported task;
- usage-only persistent status with no transfer folder configured;
- removal of enabled, paused, selected-id, and selection-version state;
- preservation of the existing folder and command ids.

### Repository And Package Guardrails

Add or update checks requiring:

- no contributed `codexUsage.sync.enabled` setting;
- no current Setup Required, Pause Sync, Resume Sync, Pull Tasks, Push Tasks, or
  persistent selected-task copy;
- no current user-facing conversation or thread terminology for Codex tasks;
- `tasks/` in packaged smoke fixtures and current documentation;
- `Unreleased` in both changelogs;
- ISO dates on every released changelog heading;
- identical dates for versions present in both changelogs.

Run the full Python and extension suites, changed-scope linting, extension build,
the local macOS Apple Silicon package smoke, and GitHub Actions Windows x64 and
macOS arm64 package smoke before publishing.

## Durable Decision Record

Add a concise ADR recording that:

- Task Transfer is manual and directional rather than an ongoing sync service;
- only the transfer folder is persisted;
- task selection is fresh for every operation;
- Import and Export use all-or-nothing preflight;
- the user-visible portable directory is `tasks/` in format version 3;
- technical CLI and thread identifiers remain unchanged;
- local baseline-state versioning is independent from remote transfer format.

The ADR supersedes the presentation and persistent-selection portions of ADR 0013
without weakening its manual-only triggers, conflict checks, or data-safety
requirements.

## Non-Goals

- Add automatic transfer triggers or background mirroring.
- Delete task files automatically after Import.
- Patch or migrate Codex's private SQLite database.
- Merge divergent task JSONL event streams.
- Rename technical thread ids, CLI commands, or `sync-index.json` fields.
- Add cloud-provider APIs or wait for provider convergence programmatically.
- Include archived tasks in transfer discovery.
- Guess missing changelog dates.
