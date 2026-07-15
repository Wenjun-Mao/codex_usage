# ADR 0012: Exact Task Sync Selection

Status: Accepted; mutation flow superseded by ADR 0013

Date: 2026-07-14

## Context

Codex presents named work items under projects as tasks, while their technical identity is a thread id. The official desktop command reference describes `codex://threads/<id>` as a local task addressed by its technical thread id. The sync UI currently calls these items conversations and supports either exact thread ids or dynamic project selection. Dynamic project selection automatically includes future tasks, and the local-only setup inventory cannot show a task that exists only in the sync folder.

This decision supersedes the selection portions of ADR 0007 and ADR 0011. It preserves their bring-your-own-folder, flat version-2 storage, one-process execution, and conflict contracts.

## Decision

Expose one read-only combined local-and-remote inventory command. The extension uses one inventory snapshot to show a project-grouped multi-select picker. Project rows select or deselect all tasks currently listed beneath them, but only exact technical thread ids are persisted and passed to sync.

New tasks remain excluded until explicitly selected. Remote-only tasks are visible and selectable. A selected id absent from both inventories remains visible as unavailable until explicitly deselected.

Use task in user-facing UI and documentation. Retain thread id in technical Python, TypeScript, JSON, CLI, and storage contracts.

Make the settings change intentionally breaking. A new selection-schema version gates sync configuration. Missing or obsolete versions ignore legacy selectors and require setup again without changing the selected folder, remote files, enabled state, or automatic-sync preferences. Do not ship migration-only code.

A technical task identity is canonical only when it is a nonempty string equal to
its own trim. Persisted, indexed, discovered, and emitted identities are never
silently trimmed. Human selector input may still be normalized before lookup, but
invalid local inventory aborts before sync can write and invalid remote index or
session identities are rejected or omitted with strict diagnostics.

Every remote index task row carries the same identity in three places: the mapping
key, `RemoteThreadEntry.thread_id`, and the required `index_entry.id`. All three must
be canonical and exactly equal before inventory exposure or pull-side metadata merge.

Treat selection schema version 2 as the setup transaction's commit marker. Setup,
reconfiguration, clear, pause, and resume share one serialized mutation queue. Each
mutation reads its previous tuple inside the queue, writes version 0 before changing
folder, exact thread IDs, or enabled state, and publishes version 2 only after every
valid tuple field is durable. A failed write restores the previous tuple and restores
its valid version last; incomplete rollback leaves version 0 so no new sync can start
from mixed state.

## Alternatives Considered

- Relabel the current picker without changing selectors. This preserves automatic future inclusion and remote-only discovery failures.
- Parse and merge the remote index in TypeScript. This duplicates sync-domain validation and violates the thin-wrapper boundary.
- Run separate local and remote inventory commands. This adds process startup and allows the two snapshots to drift.
- Keep a two-step project then task flow. It works, but a single grouped picker provides the same control with less setup friction.

## Consequences

Users configure sync again after upgrading and select exact tasks from one picker. Selecting every current task in a project remains one click, while future tasks never join silently. A second machine can discover and pull tasks that exist only in the sync folder.

The extension needs hierarchical Quick Pick state management and a strict inventory protocol. Routine status and sync remain one-process operations and use only explicit thread ids.

## Guardrails

- Project rows are current-snapshot shortcuts, never durable project subscriptions.
- Inventory is read-only and must not repair remote state on disk.
- Legacy selectors never activate the new contract implicitly.
- Technical thread IDs are nonempty and equal to their own trim at every stored or
  emitted identity boundary; normalization is limited to selector input.
- A remote index mapping key, entry thread id, and required nested index-entry id are
  exactly equal; malformed rows fail the whole remote index before inventory or pull writes.
- Selection version 2 is written last as the successful setup commit marker; version
  0 gates every in-progress mutation and every incomplete rollback.
- Deselecting a task never deletes its remote JSONL or index entry.
- User-facing copy says task; technical contracts retain thread id.
