# ADR 0032: Cross-Process Cache Refresh Recovery

## Status

Accepted; implemented in version 1.8.1 on 2026-08-29

## Context

The VS Code latest-request coordinator in ADR 0020 serializes reports inside
one extension host. Separate VS Code windows run separate extension hosts,
however, and all of them can use the same global Codex Usage SQLite cache.
Two reporters could therefore parse the same append checkpoint concurrently.
After one committed, the other attempted to insert the same `(file_key,
record_index)` rows and failed the cache's uniqueness constraint.

Codex can also move a rollout from `sessions` to `archived_sessions` while a
report is running. If that happened after fallback inventory but before open,
the direct parser failed on the stale path even though the same intact task
still existed under its archive path.

These are ownership and identity races, not malformed source data. Ignoring
duplicate rows or missing files would hide them while weakening report
correctness.

## Decision

Serialize the complete cache operation across processes with one
cross-platform file lock beside each cache database. A process acquires that
lock before collecting source inventory, then retains it through schema work,
refresh commits, storage metadata, range reads, transition refresh, and final
cache reads. Inventory is deliberately captured after lock acquisition so a
report that waited behind another process does not act on a pre-wait source
snapshot.

Before an append generation writes any rows, its SQLite transaction reloads
the parser checkpoint and requires exact equality with the checkpoint used by
the parser. A mismatch rolls back the complete commit group. The caller may
restart refresh once from current cache state; it never retries duplicate
inserts or accepts a partial generation.

The exceptional direct-parse fallback binds every discovered path to its
canonical task identity before parsing. It parses files one at a time. If one
path disappears, it refreshes identity-bearing inventory and retries only the
exact relocated task. Already parsed files are not reopened. If no exact task
identity exists, or the relocated file disappears again, fallback fails with
an explicit error rather than omitting usage.

## Rejected Alternatives

- In-process serialization alone cannot coordinate separate extension hosts.
- Treating the SQLite uniqueness failure as success cannot prove that the
  existing rows represent the same source snapshot.
- Deleting conflicting rows or using `insert or ignore` would mix generations
  and bypass the atomic checkpoint contract.
- Restarting a complete direct parse after one rename would reread an
  arbitrarily large corpus and could double-count already accumulated state.
- Silently dropping a missing file would produce a plausible but incomplete
  report.

## Consequences And Guardrails

Independent reports now queue on the shared cache instead of parsing the same
append concurrently. The wait is intentional: one process performs source and
SQLite work while later reporters reuse its committed generation and capture a
fresh post-wait inventory. The separate lock file is disposable cache state
and does not lock or modify Codex-owned JSONLs.

Tests run real competing processes, prove the waiter cannot inventory before
owning the lock, append source while it waits, and verify exactly one row per
record index. Separate tests inject a stale checkpoint at commit, require
rollback, and exercise active-to-archive relocation without reopening earlier
files. macOS Apple Silicon and Windows x64 native packaging remain release
gates because both file locking and process behavior are platform contracts.
