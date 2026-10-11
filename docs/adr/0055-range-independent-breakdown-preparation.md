# ADR 0055: Range-Independent Breakdown Preparation

Status: Accepted for local implementation, 2026-10-11. Not released.

## Context

In 2.12.0, opening a new calendar range also valued retained weekly history and
composed every continuity interval. On a frozen preview ledger, Yesterday
decoded 243,565 extra historical events and composed 733 historical intervals.
Ordinary range switches took about 15 seconds, although their calendar
composition needed only the selected day's events. Account evidence was also
partitioned again for each date/project selection.

This is a preparation-ownership problem, not a chart geometry problem. Reducing
raw quota evidence or hiding historical detail would change the evidence contract
without removing the unnecessary valuation.

## Decision

Keep three disposable preparation namespaces in `rendered_reports`:

- `breakdown-account:` owns raw account-day partitions, annotated display points,
  compact continuity directories and captured extent. Its identity binds the
  ledger, pricing, breakdown and allowance revisions, timezone, coverage and
  live evidence state: freshness, elapsed reset deadline and future anchor.
  Calendar ranges, themes, project filters and project transitions do not own
  account-wide readings or balance adjacency.
- `breakdown:` owns selected calendar composition and issued navigation. Its
  identity additionally binds calendar bounds, canonical project keys and
  transition policy. Reuse the base report's selected valuation; if this
  preparation is absent while the base is cached, query only the selection.
- `breakdown-history:` owns exact capture-causal interval composition. Its
  identity adds canonical project keys and transition policy to the account
  identity, but not the calendar range or theme. Only an exact server-issued
  interval inspection queries and values that interval, then caches its detail.

Breakdown revision 6 prevents earlier cache bodies or issued actions from being
reinterpreted. Preparation and base rendering remain pinned to one read snapshot;
a write transaction stores derived data only if the ledger revision still
matches. Strict issued-scope validation and typed expiry recovery remain intact.
Sharing account data does not allow historical project totals to cross filters.

Preserve the two existing interval contracts: calendar `[start, end)` and
capture-causal `(origin, capture]`. Keep exact valuation, calibration eligibility,
unknown/free distinctions, raw conflicts, balance adjacency and all mandatory
display boundaries unchanged. Historical aggregation retains chronological record
order rather than query/source order, including its floating-point accumulation
semantics; exact monetary parity is not relaxed to accommodate a new cache path.
No source parsing, capture, schema migration,
new pricing index or live-data mutation is introduced.

## Alternatives And Consequences

Rejected faster rendering by dropping raw readings/boundaries, using stale account
history, or sharing project-specific totals globally. These weaken accounting or
evidence rather than fixing ownership. Eagerly valuing every retained interval
for each date switch is no longer an acceptable default preparation strategy.

The first report for a new account identity still prepares retained account
evidence. A first explicit historical inspection still pays for that interval;
warm inspections reuse it. Larger selected ranges and dense report HTML remain
real costs. This is not a promise of constant-time first loads or native UI speed.

## Guardrails

`test_breakdown_navigation_work.py` asserts one account preparation across new
dates/project selections, zero historical usage queries during range switches,
lazy interval reuse, filter isolation, snapshot-race rejection and live-clock
invalidation. Existing exact interval and accounting regression tests remain.

`scripts/benchmark_range_navigation.py` compares against an exact Git authority
on temporary copies of an explicitly supplied ledger. It primes the monetary
index, clears presentation caches, fixes the clock and checks exact selected and
historical summary parity plus exact account-evidence parity. By default it also
requires unchanged base monetary/speed HTML; `--presentation-changes` explicitly
permits intentional formatting changes while retaining the exact data checks and
recording HTML equality separately. The input is
read only through SQLite backup; private evidence stays under ignored `output/`.
Measured timings are local evidence, not a general benchmark or live acceptance.

Before the companion presentation change in ADR 0056, a normal, non-profiled
run on a frozen 389,291-event ledger measured first Today/Yesterday/7-day loads
at 5.11/2.05/5.44 seconds, versus 12.68/13.95/16.37 seconds for release 2.12.0.
The candidate prepared account history once, performed zero historical usage
queries during those switches, and retained exact selected/historical and base
HTML parity. Warm Today/Yesterday were 0.34/0.38 seconds. These measurements do
not include the native VS Code webview's paint time or establish first-load
performance on other machines.

After ADR 0056's readable inspection changes, the same frozen-input protocol
measured 6.14/2.32/5.99 seconds versus 16.06/18.02/18.60 seconds for release
2.12.0, with warm Today/Yesterday at 0.39/0.43 seconds. Selected, historical and
account-evidence hashes matched exactly; base HTML deliberately differed. Local
Python, extension and script-disabled browser verification covers both changes.
