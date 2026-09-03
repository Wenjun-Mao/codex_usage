# ADR 0029: Guarded Desktop Project Binding

Status: Accepted

Date: 2026-08-15

## Context

Codex Desktop now requires explicit entries in its global
`thread-project-assignments` registry before registered tasks appear under a
project. Targeted `app-server` `thread/read` calls still repair Codex's task
catalog, but they no longer create this Desktop-only relationship. Imported
JSONLs and SQLite rows can therefore be intact while the sidebar says
`No chats`.

## Decision

When Desktop global state exists, Task Transfer Import may write only the
observed task-to-project assignment shape after file transfer and successful
Codex registration. Import resolves `CODEX_HOME`, requires Desktop to be
confirmed closed, validates the state structure, matches the destination to
exactly one existing local Desktop project by canonical real path, and rejects
conflicting task assignments before copying any files.

The commit rechecks process state plus the source file's hash and identity,
assigns only certified and successfully registered task IDs, removes those IDs
from projectless registries, and leaves project definitions, ordering, workspace
hints, rollout files, SQLite, and other state untouched. It creates a sibling
backup, writes and flushes a temporary file, atomically replaces the original,
and rereads the result. A verification failure restores the backup. Ambiguity,
concurrent change, or an indeterminate process probe fails closed.

If Desktop global state is absent, Import remains in VS Code-only mode and uses
the existing app-server registration path without creating Desktop state.

A compatibility audit against Desktop release `26.901.20858` found that current
local assignments use a compact two-field shape (`projectKind` and `projectId`),
while retained older state snapshots use the legacy four-field shape that also
contains `cwd` and `pendingCoreUpdate`. Import recognizes both exact shapes. It
writes the shape already used by that installation, prefers the compact shape
for an empty or transitionally mixed registry, and continues to reject unknown
fields. Compact assignments are destination-safe because their project ID must
resolve through the separately validated exact project root.

## Alternatives Considered

- Continue relying on `thread/read` and tell users to accept `No chats`.
- Re-export and re-import tasks after every Desktop registry change.
- Edit Codex SQLite or task JSONLs directly.
- Add missing projects, infer ambiguous projects, or rewrite the entire Desktop
  registry automatically.
- Keep a permanent migration or repair command.

## Consequences

Desktop users must add the destination checkout as a local project and quit
Desktop before Import. Successful imports tell them to start Desktop; VS
Code-only imports retain reload guidance. Unchanged re-imports still resolve a
destination, register tasks, and repair missing assignments.

This is an intentional, versioned exception to the private-state boundary. It
depends on a recognized observed state shape and must stop safely when that
shape changes. A one-time assisted recovery may use the same tested binder for
known intact local tasks, but no general repair command is retained.

## Guardrails

- Never mutate rollout JSONLs, Codex SQLite, project definitions, sidebar order,
  workspace hints, or rollout/backfill markers.
- Never write while Desktop is running or its closure cannot be established.
- Require one exact existing project path and compatible existing assignments.
- Bind only selected, certified, successfully registered task IDs.
- Recheck source identity and hash immediately before atomic replacement.
- Preserve a sibling backup and verify or roll back every committed mutation.
- Keep the binder pure apart from injected process and filesystem boundaries,
  with macOS and Windows path/process tests.

## Supersession

This ADR partially supersedes ADR 0016's prohibition on Desktop project-registry
mutation. ADR 0016's app-server registration contract and its prohibition on
direct SQLite writes remain in force. ADR 0014's manual trigger, transfer
safety, and portable-format contracts remain unchanged.
