# ADR 0035: Verified Local Project Continuity

Status: Accepted

Date: 2026-09-03

## Context

A local checkout can be repointed from an upstream repository to a fork without
changing its directory or its Git object database. Older task metadata retains
the original remote, while later work belongs to the replacement origin. URL or
folder-name matching alone could merge unrelated repositories with the same
name; retaining the old URL indefinitely instead splits one continuous project.

## Decision

Resolve the canonical checkout from `cwd`, including linked-worktree Git and
common-directory configuration. Replace a recorded repository key with that
checkout's current origin only when all of the following hold:

- the normalized origins differ;
- the session carries a syntactically valid recorded commit hash; and
- Git proves the recorded commit is an ancestor of the checkout's current
  `HEAD`.

The replacement key is canonical. The recorded key remains an alias for
filtering and for direct descendants whose metadata still names it. A child
without its own repository identity continues to inherit its parent; a child
with a repository identity inherits only when that identity is the verified
root's alias. This keeps a root task's lineage continuous without merging an
unrelated same-named repository.

The ledger rebuilds normalized project, task, context, and event ownership in
stable source-key and record-index order when its ownership normalization
version changes. Subsequent incremental event writes resolve parent identity
through the same lineage rule.

## Alternatives Considered

- Always prefer the local `origin`. It silently reattributes stale or unrelated
  tasks after a checkout is repointed.
- Merge by repository name or directory. Both identifiers collide frequently.
- Keep the recorded remote forever. This turns one verified fork replacement
  into two projects and gives descendants inconsistent ownership.
- Apply a global alias map. It is not local-checkout evidence and can affect
  unrelated histories.

## Consequences And Guardrails

Identity resolution may make one short, time-bounded local Git ancestry query.
If Git is unavailable, the hash is invalid, the commit is absent, or the
ancestry check fails, the recorded repository remains authoritative. No network
call is made. The durable ledger's one-time normalized rebuild is intentional:
it upgrades existing event ownership as a transaction rather than leaving
report reads to apply an implicit, non-durable correction.
