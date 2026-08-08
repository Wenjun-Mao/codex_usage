# ADR 0026: Guardian Approval Ownership

## Status

Accepted

## Context

A 2026-08-07 audit found 409 Task Storage groups labeled `Root missing`.
Every group contained one small structured-subagent JSONL whose source subtype
was `guardian`, whose turns used `codex-auto-review`, and whose contents were
approval-policy context, a planned tool action, and an allow or deny decision.
All 409 records exposed a valid owner in `session_id`; all also exposed a valid
immediate `parent_thread_id`, and they belonged to only nine user-visible root
tasks. They are Codex approval audit records, not missing or corrupt tasks.

The prior ownership parser recognized only
`source.subagent.thread_spawn.parent_thread_id`. It correctly kept guardians in
subagent usage totals but left their storage and backup ownership unresolved.

## Decision

Structured-subagent ownership uses this precedence:

1. `source.subagent.thread_spawn.parent_thread_id`;
2. top-level `parent_thread_id`;
3. for `source.subagent.other == "guardian"` only, `session_id` when it is
   non-empty and differs from the guardian's own `id`.

Guardian records remain structured-subagent usage under their recorded model.
Task Storage folds their bytes into the owning root tree, and a backup of that
tree preserves the guardian files. Parentless non-guardian subagents and invalid
self-ownership still produce explicit missing-root diagnostics.

Storage metadata gets an independent contract version. A stale or absent
version rereads only each file's bounded metadata prefix and updates all rows
atomically. It does not reset schema 7 or invalidate the multi-gigabyte usage
cache.

## Consequences

On the audited live corpus, the corrected grouping changed 441 apparent trees
to 32 and 409 missing-root groups to zero without changing physical-file or byte
accounting. Existing installations perform one bounded metadata refresh after
upgrading to 1.6.1; subsequent unchanged refreshes reuse those rows.

## Rejected Alternatives

- Hiding or deleting guardian files would make storage totals and backups
  incomplete.
- Treating guardians as user-visible roots would preserve the original false
  grouping.
- Rebuilding the entire usage cache would reread roughly 250 GiB to repair a
  bounded metadata contract.
- Applying `session_id` as a generic subagent fallback could silently invent
  ownership for unrelated source types.
