# ADR 0007: Bring-Your-Own Folder Selected Conversation Sync

Status: Accepted

Date: 2026-06-16

## Context

Users may work on the same Codex project across machines, but Codex did not provide automatic conversation sync. A manual handoff is easy to forget.

## Decision

Implement experimental sync through a user-provided local sync folder. Sync selected projects/conversations by copying session JSONL files, selected index entries, and manifests. Do not call cloud APIs.

## Alternatives Considered

- Sync the whole `.codex` directory. Too risky because it may include auth, config, caches, logs, SQLite, and active writes.
- Integrate directly with Dropbox, OneDrive, or another provider. More polished, but creates provider-specific dependencies and auth work.
- Keep only manual handoff. Safer, but does not solve the real switching-machine pain.

## Consequences

Users can choose any folder provider. The extension stays dependency-light. Sync setup needs careful UX because users think in projects first, then conversations.

## Guardrails

Do not sync auth, settings, caches, logs, or SQLite databases. Keep sync off until explicitly configured.

