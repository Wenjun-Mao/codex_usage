# ADR 0018: User-Visible Task Transfer Inventory

## Status
Accepted

## Context
Codex stores user tasks and internal subagent sessions in the same JSONL tree. Task Transfer also reused usage parsing and full synchronization planning before selection, causing incorrect counts and multi-minute browse latency.

## Decision
Task Transfer exposes only active sessions with valid `session_meta` and no structured `payload.source.subagent` object. Usage accounting continues to include every session. Browse inventory reads metadata, index display fields, file size, and project roots only; complete identity and content validation runs for selected IDs only.

Automatic project-transition inference remains a usage-report feature. Transfer identity uses Git metadata, declared aliases, saved roots, candidate roots, and explicit bindings so browsing never needs event-history parsing.

## Rejected Alternatives
- Parent-thread ID filtering misses parentless guardians and reviews.
- Requiring session-index membership hides valid imports during index lag.
- Exact preflight state in the picker requires hashing every task.
- Deleting old remote subagent files would make read-only browsing mutate user storage.

## Consequences
Task counts match the Codex UI, browse work scales with metadata rather than task history, and stale or changed selected files remain protected by the existing planner. Old remote subagent files remain untouched and hidden.
