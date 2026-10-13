# ADR 0058: Post-Capture Preparation Work

Status: Released in 2.12.2. Publication evidence: [release receipt](../release.md#2122-published-receipt).

## Context

The 2.12.1 navigation caches avoid repeated work while a ledger revision is
unchanged, but capture advances that revision. Profiling a read-only copy of the
reported ledger identified full task-history materialization for transition
inference, repeated checkout discovery, full-table role validation on every writer
open, duplicate quota expansion/continuity preparation, and repeated conversion
of chart observations. These costs belong to preparation, not collection fidelity
or the UI's loading indicator.

## Decision

Transition reconciliation uses the existing session/timestamp index to select
only predecessors of verified observations. Keep all timestamp ties, original
file/index order, current-generation eligibility, side-chat identity, and the
strict parsed-time comparison. Existing inference remains the oracle and final
decision maker. A task with no observations still has its old transitions removed
atomically. Resolve each distinct checkout cwd once per reconciliation; no checkout
state survives into the next capture, and commit ancestry is still verified.

Install additive partial indexes containing only invalid usage roles. Continue
running validation on every open, including NULL/invalid legacy roles; do not
replace validation with a process-global "already checked" flag. Use the same
`coalesce` predicate in the index and query, avoiding SQLite's NOT NULL predicate
simplification mismatch. Older caches are valid without these optional indexes;
the next writer creates them without a schema rebuild or parser version change.

A request-local allowance preparation object belongs to the report's pinned
SQLite snapshot. It lazily expands immutable raw evidence once and builds each
requested continuity series once. All duration buckets remain available as plan
evidence. Account and breakdown views share that preparation and the caller's
clock-bound status. It is never serialized or retained across requests/revisions.
Concurrent capture still rejects stale cache writes and uses the snapshot fallback.

Display reduction prepares each point's timestamp, exact Decimal value, series
and content identity once, reusing them across boundary detection and daily
reduction. Returned raw points, deduplication, conflicts, cross-day boundaries,
endpoints and extrema are unchanged. Hour aggregation reuses its per-day calendar,
including DST occurrences. No monetary arithmetic or cache identity changes.

## Alternatives And Consequences

Rejected skipping capture invalidation, dropping historical observations, retaining
checkout state across captures, and appending to monetary prefixes without rules
for late events or replaced generations. The cold report still reconstructs
account-wide monetary windows. Parsing, network quota probes, queueing, HTML
transfer and native painting remain separate costs; these changes do not promise
instant captures or constant-time full-history reports.

## Verification

`test_capture_preparation_work.py` checks sparse/full inference parity, timestamp
ties and offsets, side chats, duplicate archive exclusion, bounded row conversion,
per-reconciliation checkout discovery, indexed validation and corruption detection.
`test_dashboard_work_contract.py` checks one quota expansion/status query and one
preparation per series after a revision change, alongside existing snapshot-race,
clock, accounting, continuity, DST and chart-boundary regressions.

Run the release comparison on an explicit input ledger:

```sh
uv run python scripts/benchmark_capture_load.py \
  --ledger /absolute/path/to/usage-ledger.sqlite3 \
  --now 2026-10-13T02:26:12+00:00 --release v2.12.1
```

The script freezes that input via SQLite `mode=ro`, alternates release/candidate
order across three runs, and writes only disposable copies and ignored evidence.
It measures 12 recent tasks' repository/transition bookkeeping and cold/warm
reports, asserting exact transition and full HTML hashes. It reads optional local
repository/state evidence, but does not parse task bodies or make live quota RPCs.
The first additive-index installation is reported separately. Timings are local
workload evidence, not end-to-end VS Code capture/paint measurements.

On the frozen local ledger, median times across three alternating runs were:
repository plus transition bookkeeping 2.46 to 0.25 seconds; first Today after
revision 10.20 to 7.20 seconds; switching to Yesterday 1.31 to 1.26 seconds;
cached Today 0.096 to 0.041 seconds. Every paired transition and dashboard HTML
hash matched exactly. The cold-report benchmark is not the same run as the
user's 5.01-second screenshot and should not be presented as its direct replay.

Local verification: `pytest -q` passed 1,822 tests with one expected skip;
Ruff and `git diff --check` passed. A read-only independent review found no
actionable issues. Those local checks did not change an installed collector or
live ledger; subsequent release qualification is recorded in the release receipt.
