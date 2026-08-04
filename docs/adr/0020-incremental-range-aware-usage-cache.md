# ADR 0020: Incremental Range-Aware Usage Cache

## Status

Accepted

## Context

A packaged 1.0.0 audit found 2,407 current session files totaling 88.39 GiB.
Although cached usage generations were reusable, every changed file marked a
global project-transition scan dirty. That scan reopened the complete corpus,
and reports then materialized every usage row before filtering in Python.

The usage cache is disposable derived data, not user-owned state. The new
incremental contract also needs to preserve complete file generation recovery,
parent-only SQLite ownership, and exact current-source reporting.

## Decision

Schema 4 is the only supported internal cache format and uses
`usage-cache-v4.sqlite3`. An incompatible cache is rebuilt once by dropping
only known plugin-cache objects and recreating the schema; old rows are not
migrated. The first 1.1.0 report therefore performs one intentional rebuild.

Each changed JSONL is parsed in one pass by a usage worker that also returns
raw workdir candidates and source metadata. The parent process owns candidate
verification and SQLite transactions, so no worker opens SQLite or verifies a
mutable repository path. A failed parse, transport, or verification preserves
the previous complete file generation.

Dirty transition ownership is per task. The parent refreshes transitions only
for tasks affected by changed, new, removed, or repaired generations; it keeps
unaffected task transitions. Range-aware SQLite queries use UTC-microsecond
bounds, then perform an indexed parent identity lookup for selected records
that inherit task identity from a parent outside the range.

The extension serializes refreshes by latest request. One running process is
allowed to finish with its worker tree and transaction intact, one pending
request is replaced by newer settings, and obsolete results are not rendered.

## Rejected Alternatives

- Caching rendered HTML: every report setting and source-generation change
  would create another invalidation key without improving source freshness.
- Byte offsets or append checkpoints: truncation, partial-line recovery, and
  interruption semantics would add a new generation contract.
- Schema migration or dual reads: preserving unsupported derived rows would
  retain incomplete candidate history and multiply test paths.
- Cancelling obsolete processes: cross-platform worker-tree termination could
  interrupt parent SQLite work; latest-request serialization avoids that risk.

## Consequences And Guardrails

The first report rebuilds schema 4 from source, while later reports inspect
only changed files. Cache commits retain complete file generation recovery and
the parent remains the only SQLite writer. Source and frozen acceptance prove
cold combined-worker parallelism, zero warm transition spans, one changed-file
span, and a separate cold semantic oracle. Native pre-publish gates cover
macOS Apple Silicon and Windows x64 packages.
