# ADR 0016: Register Imported Tasks Through Codex

Status: Accepted

Date: 2026-07-23

## Context

Task Transfer Import copied valid rollout JSONLs, rewrote their cwd, and updated
`session_index.jsonl`, but modern Codex clients list tasks from their state
database. Codex's one-time rollout backfill does not rescan files copied after
the backfill completes. Earlier successful imports depended on an incidental
filesystem read repair while a Codex client was running.

## Decision

After a certified Import, invoke an installed official Codex executable as a
short-lived `app-server` and issue targeted `thread/read` requests for imported
task ids. Codex performs its own supported read repair and state update.

Register every selected task after a completed Import, including unchanged tasks,
so re-running Import heals tasks copied by older versions. After a partial Import,
register only task copies whose completion is certified. Keep the files when
registration fails and report partial completion with retry guidance.

Discover official Codex runtimes from the official VS Code extension, the native
desktop app for Windows or macOS, and `PATH`. Do not require the desktop app when
another official runtime is available.

## Alternatives Considered

- Continue relying on client restart or incidental filesystem scans.
- Run a filesystem-wide non-state-database task listing after every Import.
- Insert task rows directly into Codex's private SQLite database.
- Reset Codex's completed rollout-backfill marker.
- Roll back safely imported files when registration fails.

## Consequences

Imported tasks become deterministically discoverable on Windows x64 and macOS
Apple Silicon. The running Codex sidebar may remain cached, so users are told to
open or restart Codex, or reload VS Code, after registration.

Import now has two observable boundaries: portable file transfer and Codex
registration. A registration error can produce partial completion even when all
files were transferred safely. Re-running an unchanged Import retries
registration without requiring a migration.

## Guardrails

- Use only Codex's supported app-server protocol for registration.
- Never write, migrate, or verify private Codex SQLite rows directly.
- Never modify Codex desktop project registries or reset backfill state.
- Issue only initialization and targeted task-read requests; never start a turn
  or invoke a model.
- Register only completed Imports or certified partial `issue` results. Reject
  the whole registration batch when pulled ids are noncanonical, duplicated,
  inconsistent with the result count, or outside the selected task set.
- Bound child-process lifetime, output, retries, and request timeouts. Await
  graceful process-tree shutdown, then force and bound tree termination before
  settling the registration attempt.
- Do not roll back certified task files after registration failure.
- Keep client restart/refresh under user control.

## Supersession

This decision supersedes ADR 0014's blanket prohibition on updating Codex state.
ADR 0014's prohibition on direct private-database and project-registry mutation
remains in force. All manual-trigger, transfer-safety, destination-resolution,
and portable-format decisions in ADR 0014 remain unchanged.
