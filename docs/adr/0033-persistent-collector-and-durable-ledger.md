# ADR 0033: Persistent Collector And Durable Usage Ledger

## Status

Accepted for version 2.0.0 on 2026-09-02

## Context

The 1.x product refreshed usage only while a VS Code extension host was alive.
That made report loading responsible for source parsing and could permanently
miss the uncaptured tail of a task deleted before another report. Large active
rollouts also made repeated whole-file work unacceptable: a single task can be
many gigabytes and can remain active for hours or days.

The product needs durable historical accounting without requiring VS Code,
Codex Desktop, or a model turn to be running. It also needs bounded idle I/O;
a continuously running collector must not repeatedly read task content merely
because it is alive.

## Decision

Run one independent per-user Python capture agent for one active `CODEX_HOME`.
When the user opts into background capture, a LaunchAgent on macOS or Scheduled
Task on Windows keeps it available after the app closes. The default interval
is 15 minutes, configurable from 1 minute through 24 hours or Manual Only.
Manual Capture Now requests coalesce with scheduled work and reset the interval
after successful completion.

Background registration is an explicit first-run choice and starts unchecked;
opening the native app alone must not install persistent operating-system state.

Store usage in a forward-migrated SQLite ledger under
`CODEX_HOME/.codex-usage/usage-ledger.sqlite3`. The agent is its only writer;
clients use an authenticated versioned loopback API. Missing source files keep
their last trusted generations. Reports query only the ledger and cache their
rendered result by ledger and pricing revisions.

Health probes have a short timeout, while authenticated operation requests have
no aggregate client timeout. Large local transfers and first-run migrations can
legitimately exceed ten minutes; abandoning only the client wait would report a
false failure while the single agent-owned operation continued. Request and
response size bounds, job coalescing, and the heavy-I/O lane remain the resource
guards.

Filesystem notifications only mark paths dirty. Interval reconciliation may
stat sources but opens no unchanged JSONLs. Guarded checkpoints read fixed
verification windows plus append tails. Mismatches preserve the trusted
generation while low-priority, chunked reconstruction builds a replacement in
staging. A single prioritized heavy-I/O lane prevents capture, transfer,
reconstruction, and explicit storage analysis from competing.

Every discovered source receives an inventory row before a bounded parse slice
is scheduled. Baseline coverage therefore includes files that have not yet
entered the parser workset; partial totals can never appear complete merely
because the current slice omitted them.

Onboarding migration compares complete usage context, stable task metadata,
and repository-transition evidence rather than token counters alone. Prefix
histories merge automatically; divergent histories require one explicit source
choice that also governs related transition rows.

## Rejected Alternatives

- Keeping refresh inside VS Code leaves capture unavailable whenever VS Code is
  closed and couples reports to corpus parsing.
- Codex hooks do not cover long-running turns or abrupt shutdown and would add
  another lifecycle contract without replacing periodic reconciliation.
- A Docker service adds filesystem, startup, and desktop-integration friction
  without improving local ownership or I/O behavior.
- A cloud ledger would require uploading sensitive local task metadata and is
  outside this product's local-only contract.
- Continuous content parsing would reduce latency but impose needless I/O on
  very large active files. A 15-minute default is a better reference-data
  tradeoff, with Capture Now for explicit freshness.

## Consequences And Guardrails

Usage survives normal source deletion once captured, dashboard range changes
open zero JSONLs, and an opted-in collector remains independent of both Codex
and the UI. A manual deletion can still lose an uncaptured tail; product copy
must direct users to Capture Now before deleting a task.

SQLite uses WAL, foreign keys, bounded transactions, backup-protected forward
migrations, and one writer. Watcher callbacks never parse. Baseline progress
must be visibly incomplete until complete, and stale generations remain
explicit rather than silently replacing trusted history. Tests enforce zero
source opens on unchanged cycles, bounded append reads, fair chunk scheduling,
coalescing, sleep/wake recovery, singleton ownership, and atomic replacement.
Agent descriptors, databases, and service log directories are owner-readable
only.
