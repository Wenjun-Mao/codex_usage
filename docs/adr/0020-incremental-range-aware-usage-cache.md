# ADR 0020: Incremental Range-Aware Usage Cache

## Status

Accepted. Cache ownership is partially superseded by
[ADR 0033](0033-persistent-collector-and-durable-ledger.md). Whole-file refresh
and no-checkpoint behavior were previously partially superseded by
[ADR 0022](0022-guarded-append-parser-checkpoints.md). Per-task
transition ownership, range-aware queries, latest-request serialization, and
parent-only SQLite ownership remain in force. Latest-request serialization is
per extension host; [ADR 0032](0032-cross-process-cache-refresh-recovery.md)
adds the required cross-process cache boundary.

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

Each changed JSONL was originally parsed from byte zero in one pass by a usage
worker that also returned raw workdir candidates and source metadata. ADR 0022
allows a guarded active-file append to resume from a serialized parser
checkpoint. The parent process still owns candidate verification and SQLite
transactions, so no worker opens SQLite or verifies a mutable repository path.
A failed parse, transport, or verification preserves the previous complete
file generation.

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
- Unguarded byte offsets or independently committed append checkpoints:
  truncation, partial-line recovery, and interruption semantics would create an
  unsafe second generation contract. ADR 0022 incorporates those concerns into
  the existing atomic generation contract.
- Schema migration or dual reads: preserving unsupported derived rows would
  retain incomplete candidate history and multiply test paths.
- Cancelling obsolete processes: cross-platform worker-tree termination could
  interrupt parent SQLite work; latest-request serialization avoids that risk.

## Consequences And Guardrails

The first 1.1.0 report rebuilt schema 4 from source. Schema 6 now replaces that
disposable format as described by ADR 0022. Cache commits retain complete file
generation recovery and the parent remains the only SQLite writer. Source and
frozen acceptance prove cold combined-worker parallelism, zero warm transition
spans, one changed-file span, and a separate cold semantic oracle. Native
pre-publish gates cover macOS Apple Silicon and Windows x64 packages.
