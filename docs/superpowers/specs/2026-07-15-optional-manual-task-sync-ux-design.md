# Optional Manual Task Sync UX Design

Date: 2026-07-15

Status: Approved

## Goal

Make Codex Usage clearly usable as a token-usage dashboard without task sync, and
make optional task transfer read as a small set of explicit manual commands.

The next release removes the legacy enabled/paused sync state, improves transfer
feedback, finishes the task-versus-thread terminology boundary, and dates both
changelogs without changing the Python transfer protocol or remote sync format.

## Root Cause Note

### What Failed

The status bar can show `Codex Usage: 7d Sync: Setup required`. This makes optional
task sync look like a prerequisite for token-usage reporting. A no-op Pull reports
`Pulled 0 tasks`, which is numerically correct but does not explain whether the
tasks are already current, need the opposite direction, or failed.

The manual-only model also still exposes **Pause Sync**, **Resume Sync**, and a
`codexUsage.sync.enabled` setting. Those controls imply a background service even
though transfers run only after an explicit Pull or Push command.

### Why It Failed

The presentation model still inherits state and copy from the former automatic
sync design. It combines the dashboard's persistent usage status with optional
task-transfer setup, and it treats a manual command gate as though it were a
runtime synchronization state.

Several user-facing surfaces also leak implementation vocabulary:

- task pickers display `Thread ID`;
- availability uses `local`, `remote`, and `Both` wording;
- menu details refer to remote changes and a bring-your-own folder;
- current documentation says to keep Sync Enabled on;
- current release headings omit release dates.

### Evidence

- `syncStatusBadge` returns `Sync: Setup required` for an invalid selection and
  appends it directly to the usage status-bar text.
- `syncControlLabel` exposes the same setup-required wording in the dashboard.
- `SyncSettings`, `SyncSetupState`, and the setup transaction all persist an
  `enabled` boolean.
- the Sync menu offers Pause or Resume even though ADR 0013 prohibits automatic
  activation, focus, timer, and file-watcher transfers;
- completion notifications report only the number transferred plus pending work;
- `syncTaskPicker.ts` displays technical thread ids as `Thread ID`;
- both changelogs have version headings without ISO release dates.

### Correct Fix Layer

This is not only a copy defect. The durable fix is to remove the invalid
enabled/paused state from the extension contract, make configuration validity the
only setup predicate, and give task-transfer presentation one focused owner.
Relabeling Pause and Resume would preserve the false background-service model.

## Product Contract

Codex Usage token reporting is always available and never requires task sync.

Task sync is optional and manual:

- **Pull Tasks** copies selected changes from the sync folder to this device.
- **Push Tasks** copies selected changes from this device to the sync folder.
- **Task Sync Status** inspects selected task state without copying files.
- no transfer runs on activation, focus, a timer, a file watcher, or an enabled
  setting.

A task-sync setup is configured when and only when it contains:

- a nonblank sync folder;
- selection schema version `2`;
- at least one exact technical thread id.

Configuration stores intent. It does not enable a background process.

## Remove The Legacy Enabled State

Remove `enabled` from:

- the contributed `codexUsage.sync.enabled` setting;
- `SyncSettings` and webview state;
- `SyncSetupState`, `CommittedSyncSetup`, and `AsyncSyncSetupStore`;
- setup commit, clear, rollback, and serialization logic;
- runtime guards and status rendering;
- menu actions and tests for Pause and Resume.

Remove `off` from the runtime status-kind contract. `idle` is the neutral runtime
state. The remaining states are `idle`, `scanning`, `pulling`, `pushing`,
`conflict`, and `issue`.

Clearing task-sync setup removes the selected folder, selected ids, and selection
version through the existing transactional invalidation and rollback sequence. It
does not delete local Codex files or anything in the sync folder.

## Upgrade Migration

At extension activation, inspect the global, workspace, and workspace-folder
configuration scopes for an explicit legacy `codexUsage.sync.enabled` value and
remove every such value because the setting no longer has valid behavior. The
migration must be idempotent.

Migration preserves:

- the selected sync folder;
- selection schema version `2`;
- selected technical thread ids;
- all local and remote task files;
- the remote catalog and local paired baselines.

A previously paused but otherwise valid setup becomes a normal configured setup.
Nothing transfers until the user explicitly invokes Pull or Push.

Failure to remove an obsolete configuration value is written to the Codex Usage
output channel but cannot block activation, token reporting, or task transfer.
Runtime behavior ignores the obsolete value regardless.

## Presentation Ownership

Add a focused `syncPresentation.ts` module for pure task-sync presentation:

- runtime status labels;
- dashboard control labels;
- configured and unconfigured menu items;
- status-bar suffixes and tooltip copy;
- completion-message formatting.

Move the existing sync presentation helpers out of `core.ts`, and keep VS Code API
calls and orchestration in `extension.ts`. This reduces responsibilities in two
files already above 500 lines and makes the complete message matrix directly
unit-testable.

The Python models, JSON protocol, planner, storage layer, and transfer execution
remain unchanged.

## Status Bar And Dashboard

### Status Bar

When task sync is unconfigured or idle, show only the usage status:

```text
Codex Usage: 7d
Codex Usage: 7d (2)
```

Append task-sync text only for active or actionable runtime states:

```text
Codex Usage: 7d | Pulling tasks
Codex Usage: 7d | Pushing tasks
Codex Usage: 7d | Task sync conflict
Codex Usage: 7d | Task sync issue
```

`scanning` uses `Checking selected tasks`. The status returns to usage-only after
a successful command reaches idle.

The usage tooltip explicitly states one of:

- `Task sync is optional and is not configured.`
- `Task sync is configured for 2 selected tasks.`

### Dashboard Control

Use these persistent dashboard labels:

```text
Task Sync: Set up (optional) ▾
Task Sync: 1 selected ▾
Task Sync: 2 selected ▾
```

The control opens the Task Sync menu; it does not imply that setup is required for
the dashboard.

## Task Sync Menu

An unconfigured menu contains one primary item:

- **Set Up Task Sync**: choose the sync folder and exact Codex tasks.

A configured menu contains:

- **Pull Tasks**: copy changes from the sync folder to this device;
- **Push Tasks**: copy changes from this device to the sync folder;
- **Task Sync Status**: inspect selected tasks without copying;
- **Change Folder**;
- **Change Tasks**;
- **Forget Task Sync Setup**;
- **Open Sync Folder**.

Remove Pause and Resume completely. Existing command ids remain stable where only
their display titles change. Direct Pull, Push, or Status invocation without a
valid setup says `Task sync isn't configured.` and offers **Set Up Task Sync**.

## Completion Feedback

Completion copy distinguishes transfer count from overall selected-task state.
Use the result's selected task rows and planned opposite-direction actions rather
than inferring success from the transferred count alone.

### No Transfer Needed

```text
No tasks needed pulling. All 2 selected tasks are up to date.
No tasks needed pushing. All 2 selected tasks are up to date.
```

### Files Transferred

```text
Pulled 2 tasks. Restart Codex to load pulled changes.
Pushed 2 tasks to the sync folder.
```

Every successful Pull with at least one copied task includes the restart guidance.
A zero-copy Pull does not claim that a restart is needed.

### Opposite Direction Still Needed

After Pull:

```text
1 selected task has changes on this device. Use Push Tasks to copy it to the sync folder.
```

After Push:

```text
1 selected task has changes in the sync folder. Use Pull Tasks to copy it to this device.
```

When a command both transfers tasks and leaves opposite-direction work, combine
the transfer sentence and the actionable sentence. Preserve correct singular and
plural grammar.

### Conflict And Issue Copy

Use task-sync and command names rather than generic `Codex sync` or `Codex pull`:

```text
Task sync found 1 conflict. Open Task Sync Status for details.
Pull Tasks could not complete: <actionable issue>.
Push Tasks could not complete: <actionable issue>.
```

Technical diagnostics remain in the output channel.

## Terminology Contract

User-facing extension UI and current-behavior documentation use:

- task and tasks;
- Task ID and Task IDs;
- this device;
- sync folder;
- On this device, In sync folder, and On both;
- estimated transfer size.

Technical contracts retain:

- `thread_id` and `threadIds`;
- `--thread-id`;
- the `threads` CLI command;
- the `conversations/` storage directory;
- protocol values `local`, `remote`, and `both`;
- low-level output diagnostics where implementation identities matter.

The task picker presents a technical identity as `Task ID`, even though the value
is the underlying thread id. Project-transition UI uses `Task IDs`; transition
JSON continues to use `thread_ids`.

Replace vague or outdated current UI copy including:

- `Setup required` and `Setup needed`;
- `Thread ID` and `Threads` for Codex sidebar items;
- `Import remote changes` and `Publish local changes`;
- `local/remote state`;
- `bring-your-own sync folder`;
- `Sync Enabled`, Pause Sync, and Resume Sync.

Historical changelog bullets may retain terminology that accurately describes a
former release. Current README and Marketplace documentation must use the new
contract.

## Documentation And Changelog Policy

The root README and extension README state near the start of task-sync coverage
that token reporting works without task sync. Update current instructions,
screenshots or literal status examples, command names, archived/deleted task copy,
and manual transfer guidance.

Both changelogs gain an undated top section:

```text
## Unreleased
```

Released headings use ISO dates while preserving descriptive titles when present:

```text
## 0.1.35 - 2026-07-14 - Manual Cross-Platform Task Transfer
```

Backfill each existing heading with the date of the commit that first introduced
that release heading. The root changelog is the canonical source when an extension
entry was copied later. Matching versions in both files must use identical dates.
No date is guessed.

Future notable changes start under `Unreleased`. Release preparation moves those
changes into the new version heading and records the actual release date.

## Error Handling

- An unconfigured direct command offers setup and performs no discovery or write.
- A setup mutation failure rolls back folder, task ids, and version atomically.
- A transfer conflict or structured issue preserves the existing planner outcome
  and performs no weaker presentation-layer workaround.
- A completion formatter must not call a zero-transfer result a failure.
- A zero-transfer result must not claim all tasks are current when the result still
  contains opposite-direction work.
- Migration cleanup failure is non-blocking because the obsolete setting no longer
  participates in behavior.
- Sync never patches Codex SQLite. Restart guidance is presentation, not a private
  database mutation.

## Testing And Guardrails

Use test-driven implementation.

Add pure TypeScript tests for:

- configured and unconfigured dashboard labels;
- every runtime status-bar suffix;
- configured and unconfigured menu contents;
- singular and plural completion messages;
- zero-transfer up-to-date and opposite-direction cases;
- Pull restart guidance only when at least one task was copied;
- Task ID and device/sync-folder terminology.

Update setup transaction and migration tests to prove:

- no enabled state remains in the setup contract;
- valid folder/task selections survive upgrade;
- clear and rollback remain atomic;
- obsolete explicit configuration values are ignored and cleanup is idempotent.

Add metadata and documentation guardrails that require:

- no contributed `codexUsage.sync.enabled` setting;
- no Pause or Resume menu copy;
- no current `Setup required` UI copy;
- an `Unreleased` heading in both changelogs;
- ISO dates on every released heading;
- identical dates for versions present in both changelogs.

Run the full Python and extension test suites, changed-scope linting, the local
macOS Apple Silicon package smoke, and GitHub Actions Windows x64 and macOS arm64
package smoke before publishing the next release.

## Durable Decision Record

Implementation adds a concise ADR because removing enabled/paused state changes a
durable runtime and configuration contract. The ADR records that task transfer is
optional, configured-or-unconfigured, and exclusively command-driven. It also
records the legacy-setting migration and rejects relabeling a manual-command gate
as an alternative.

## Non-Goals

- Change Python sync planning, transfer, hashing, or conflict semantics.
- Change the version-2 remote catalog or `conversations/` layout.
- Patch or migrate Codex's private SQLite database.
- Add automatic transfer triggers.
- Rename technical CLI or JSON fields.
- Reconstruct release dates from memory or approximate publication windows.
