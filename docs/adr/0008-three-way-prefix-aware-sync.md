# ADR 0008: Three-Way Prefix-Aware Sync

Status: Accepted

Date: 2026-06-16

## Context

Two-way hash comparison treated any local/remote difference as a conflict. That blocked normal workflows where one machine simply appended new Codex JSONL events.

## Decision

Track base/local/remote state per conversation and sync folder. Treat append-only prefix relationships as fast-forwards. Treat divergent non-prefix tails as conflicts.

## Alternatives Considered

- Always overwrite local with remote or remote with local. Unsafe.
- Always report any difference as conflict. Safe but too noisy.
- Merge JSONL records by timestamp. Tempting, but risky because event order may matter and duplicated/replayed context exists.

## Consequences

Normal one-machine progress can sync automatically. True divergent edits stop before overwriting either side. The sync engine needs local base-state files.

## Guardrails

Status and execution must use the same planner. Manual sync can surface conflicts visibly; automatic sync should use quiet status plus rate-limited action-needed notifications.

