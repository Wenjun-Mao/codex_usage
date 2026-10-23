# ADR 0072: In-Process SQLite Writer Admission

Date: 2026-10-18. Status: implemented locally; not released or installed.

## Problem And Evidence

The collector coalesces scheduled/manual captures on one heavy-I/O lane, but
threaded report requests also write allowance calculations and rendered caches.
A cold allowance calculation owns a SQLite write transaction throughout its
calculation. A capture on another thread can exceed the unchanged five-second
SQLite busy timeout. Even recording its failure can then fail, leaving the audit
row marked running after the request has already failed.

The reported 2.12.5 incident had database-lock errors in the dashboard log and an
unfinished manual-capture audit row. Those logs do not retain the historical
Python stack. A synthetic concurrent cold-report/capture regression independently
reproduced both the quota-write failure and the subsequent failure-audit write
before the fix. It shortens only the test's SQLite timeout to avoid a slow test.

The violated contract is one admitted writer inside the collector process, not
the safety of the underlying accounting data. Reports' read-only snapshots and
revision-pinned cache publication must remain concurrent and unchanged.

## Decision

Writable ledger and parser-cache connection contexts share one reentrant,
process-local admission lock per canonical database path. Wait before opening
SQLite, including schema/tracking preparation, and retain ownership through
connection close and cleanup. Readers do not acquire admission. Different
databases remain independent; same-thread nested connection setup is reentrant.
This does not permit nested SQLite write transactions on separate connections.

The registry counts owners and waiters and removes unused entries, including on
exceptions. It creates no persistent lock file, daemon, retry or data migration.
The existing home-agent lock, cross-process parser-refresh/maintenance fencing,
writer authorization, transaction boundaries and SQLite busy timeout are retained.
Uncoordinated writers in other processes can still produce SQLite contention;
this lock is not cross-process protection or permission to bypass maintenance.

## Consequences And Guardrails

Capture waits for an owned cold report writer instead of racing it to SQLite's
busy timeout. Read-only status/report snapshots remain usable while waiting.
This fixes the reproduced failure class, not the duration of cold allowance work
or 30-day report loading. Moving expensive cache computation outside write
transactions remains a separate performance/design investigation.

Rejected increasing the busy timeout, retrying an entire partially completed
capture, suppressing failures or resetting/deleting ledger and lock files. None
establishes the missing writer-admission contract.

Regressions cover an actual cold allowance build against capture, successful
completion and original-error auditing, both ledger/parser entrypoints, concurrent readers,
independent databases, nested setup, canonical aliases and exception cleanup.
Existing oracle, snapshot-revision, rollback, writer-fencing and cross-process
refresh tests remain required. No live capture, repair, collector restart or
installed-extension change is part of local verification.

Local verification passed: full Python suite 3,285 passed with one existing skip;
the final six-case contention suite also passed after adding the original-error
variant. Ruff, exact monetary parity and bounded-work checks passed. The monetary
snapshot hash remains
`58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`.
