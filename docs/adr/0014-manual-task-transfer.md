# ADR 0014: Manual Task Transfer

Status: Accepted

Date: 2026-07-16

## Context

The product presented explicit file transfers as ongoing Sync. It remembered task
selections, exposed enabled and paused state, and treated Codex desktop saved
workspace roots as the primary destination lookup. Those choices implied a
continuously mirrored relationship and made the desktop app appear required even
though every transfer ran only after a user command.

## Decision

Present the feature as optional **Task Transfer** with three deliberate operations:
**Import Tasks**, **Export Tasks**, and **Review Transfer Status**. Persist only the
transfer-folder path. Every operation starts with a fresh task selection and uses
an all-or-nothing preflight before copying any selected task.

Resolve import destinations from surface-neutral roots: an existing local
task cwd, active VS Code workspace folders, optional desktop saved roots, or a
folder chosen for the current Import. Validate Git-backed mappings by normalized
origin. Require explicit confirmation for an unverifiable non-Git mapping. Preserve
the native cwd of an existing local task and apply transient mappings only to
remote-only tasks.

Do not write Codex private SQLite, global-state, or project-registry data. The
portable format is version 3 and stores JSONLs under `tasks/`; valid version-2
folders migrate automatically. Remote format version 3 and local paired-baseline
version 2 are independent contracts.

## Alternatives Considered

- Change wording while retaining setup, enabled, paused, and saved-selection state.
- Persist cross-computer project mappings or task selections.
- Require the Codex desktop app and its private saved-root registry.
- Run automatic background transfers from activation, focus, timers, or watchers.
- Patch Codex SQLite or private global state to register imported tasks.

## Consequences

Token reporting remains independent from Task Transfer. A corresponding project
checkout must already exist locally, but extension-only imports can use an open VS
Code workspace without the desktop app. Imports leave source files in the transfer
folder, and version-2 folder migration is automatic. Technical `sync`, `pull`,
`push`, and `thread_id` vocabulary remains private implementation terminology.

Current packages remain Windows x64 and macOS Apple Silicon only. Linux packaging
is a follow-up rather than a supported target in this release.

## Guardrails

- Transfer only after an explicit Import, Export, or Review command.
- Validate the complete selected batch, project identity, and path safety before
  copying any task.
- Preserve an existing local task's cwd and never persist a transient binding.
- Block conflicts, malformed structures, changed sources, and opposite-direction
  actions without partial copies.
- Keep Codex private databases and registries read-only.
- Do not add a Linux package in this release.

## Supersession

This decision supersedes ADR 0013's user presentation, persistent selection, and
desktop-root discovery portions. ADR 0013's explicit manual triggers, directional
mutation boundaries, conflict preflight, atomic replacement, backup, and
observable-boundary validation rules remain in force.
