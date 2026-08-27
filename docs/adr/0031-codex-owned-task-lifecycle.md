# ADR 0031: Codex-Owned Task Lifecycle

## Status

Accepted; implemented in version 1.8.0 on 2026-08-27

## Context

Codex Usage added a custom compressed task-tree archive and a rollover
preparation workflow before Codex exposed a practical manual continuation
path. The archive had a strict integrity contract, but the plugin never
implemented restore. Maintaining a private lifecycle format without a complete
restore path adds code, dependencies, UI surface, and user expectations while
remaining separate from Codex's own task registry and lifecycle behavior.

Task Storage's durable value is read-only inventory and evidence-based content
diagnostics. Continuation and storage reduction have different goals: a Codex
fork favors conversational continuity, while a fresh task with a concise
handoff avoids inheriting as much prior context. Neither operation should be
presented as a backup.

## Decision

Version 1.8.0 removes custom task backup creation, verification, and rollover
preparation from the Python CLI and VS Code extension. Task Storage retains
only snapshot inventory and selected-tree analysis. Its only writes are to the
disposable diagnostic cache.

Users manage task lifecycle manually in Codex:

- use **Fork in Codex** for conversational continuity;
- use a fresh task with a concise handoff when reducing inherited context and
  future storage growth is the priority; and
- verify the replacement before manually archiving or deleting the original.

The plugin does not automate forking, task creation, archiving, restoration, or
deletion. Existing `.codex-task-backup` files are user-owned and remain
untouched, but Codex Usage no longer creates, verifies, or restores them. Task
Transfer remains a separate cross-computer transport workflow and is not a
backup mechanism.

## Consequences

Task Storage has a smaller attack surface, no compression dependency, and a
clear read-only product boundary. Users no longer receive a plugin-specific
archive or rollover checklist. Forking may retain substantial context and disk
usage; a fresh task is the appropriate choice when reducing inherited state is
more important than exact conversational continuity.

## Rejected Alternatives

- Keeping the commands as hidden compatibility stubs would preserve a format
  the product no longer supports and obscure the breaking contract.
- Automating Codex forking would duplicate a Codex-owned lifecycle operation
  and couple the plugin to private behavior.
- Describing Task Transfer as backup would confuse transport with retention and
  recovery guarantees.

## Guardrails

- CLI and extension command manifests expose only Task Storage snapshot and
  analysis operations.
- Storage snapshot schema 4 contains no backup- or rollover-readiness fields.
- Current product documentation distinguishes a fork from a backup and from a
  fresh-task storage strategy.
- Historical ADRs and changelog entries remain available, with their
  superseded status explicit.
