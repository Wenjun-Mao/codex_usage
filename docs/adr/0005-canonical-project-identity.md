# ADR 0005: Canonical Project Identity

Status: Accepted

Date: 2026-06-16

## Context

Codex session metadata can include a git repository URL, only a working directory, or stale project information after forks and repo renames. Project labels can collide.

## Decision

Use canonical project keys for grouping. Prefer JSONL git repository URL. If missing, resolve the local git origin from `cwd`. Normalize common HTTPS and SSH remotes. Fall back to normalized paths and keep aliases for backwards-compatible filtering.

## Alternatives Considered

- Group by display label. Easy, but merges unrelated projects with the same folder name.
- Group only by `cwd`. Stable locally, but splits the same repo across machines or reclones.
- Group only by JSONL git metadata. Fails when metadata is missing.

## Consequences

Project breakdowns are more stable. Some cases, such as repo renames mid-conversation, require transition detection in addition to identity resolution.

## Guardrails

Do not merge by label alone. Keep aliases so old filters continue to work.

