# ADR 0018: User-Visible Task Transfer Inventory

## Status
Accepted

## Context
Codex stores user tasks and internal subagent sessions in the same JSONL tree. Task Transfer also reused usage parsing and full synchronization planning before selection, causing incorrect counts and multi-minute browse latency.

## Decision
Task Transfer exposes only active sessions with valid `session_meta` and no structured `payload.source.subagent` object. Transfer metadata is a stricter contract than usage parsing: `session_meta.payload` must be an object with an explicit canonical `id`. Local and remote browse use one transfer-specific reader that examines at most the first 1 MiB and retries transient filesystem failures with bounded exponential backoff. Missing, malformed, or later metadata produces a structured unreadable issue. Usage accounting and its tolerant session reader remain unchanged.

Browse inventory reads metadata, index display fields, file size, and project roots only. After selection, local task bytes are read once for metadata and the complete SHA-256. Canonical ID, root provenance, and project identity must match the browsed task before the resulting snapshot can enter planning. Existing containment, prefix, baseline, conflict, and post-planning concurrent-change checks continue to guard execution.

Version-3 status and execution discovery keep every unselected indexed or unindexed remote task metadata-only, including the locked planning pass. Only explicitly selected task IDs are upgraded to same-snapshot complete bytes and SHA-256. Version-2 stores remain an intentional exception: migration validation reads and hashes the complete legacy corpus before any version-3 selection optimization applies.

Automatic project-transition inference remains a usage-report feature. Transfer identity uses Git metadata, declared aliases, saved roots, candidate roots, and explicit bindings so browsing never needs event-history parsing.

## Rejected Alternatives
- Parent-thread ID filtering misses parentless guardians and reviews.
- Requiring session-index membership hides valid imports during index lag.
- Exact preflight state in the picker requires hashing every task.
- Deleting old remote subagent files would make read-only browsing mutate user storage.
- Reusing the usage metadata reader would preserve fallback IDs, tolerate malformed payloads, and make browse work scale with history length.
- Parsing selected metadata separately from hashing would allow provenance and content checks to observe different file versions.

## Consequences
Task counts match the Codex UI, browse work is bounded by metadata rather than task history, and stale or changed selected files remain protected by both same-snapshot validation and the existing planner. A legitimate `session_meta` larger than 1 MiB is treated as unreadable and must be corrected before transfer. Old remote subagent files remain untouched and hidden.
