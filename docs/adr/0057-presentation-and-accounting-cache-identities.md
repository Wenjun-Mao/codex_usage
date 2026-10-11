# ADR 0057: Presentation And Accounting Cache Identities

Status: Released in 2.12.1, 2026-10-11.

## Context

Profiling the frozen preview ledger after ADR 0055 showed repeated pricing-table
hashes for every event, repeated economics aggregation, duplicated account-status
queries, and chart rendering on warm navigation. Package-version-based monetary
identity also forced repricing for presentation-only releases. These are cache
ownership and repeated-work problems, not reasons to weaken evidence retention.

## Decision

Compile immutable pricing schedules in a bounded identity-keyed cache that retains
the original tuple. Replacing a schedule recompiles it; per-event lookup does not
hash every rate. Retain existing lookup and floating-point accumulation order.
Economics coverage consumes already-computed totals and turn metrics.

Monetary cache identity includes the canonical effective API/credit schedules,
aliases, included-review boundary, image-pricing revision and explicit language
accounting revision. It excludes package and render versions. Changes to accounting
arithmetic must bump the language accounting revision; rate changes invalidate by
content. The first rollout replaces the previous conservative package identity.

One snapshot supplies account status using the report clock. Share rendered
allowance HTML across selected dates/projects while binding account revisions,
timezone, theme, render revision, local day, freshness and pace presentation state.
Selected totals remain separately scoped. Do not decode full historical accounting
again merely because the calendar range changed.

Breakdown revision 7 adds a render-revision-bound raw HTML section cache. Issued
navigation remains compact structured data. A missing navigation row rebuilds the
section; a cached chart never issues actions without their matching directory.
Writer revision checks and fresh navigation receipts remain mandatory. Raw
account evidence, conflicts and capture-causal interval ordering are unchanged.
Base report and shared allowance fragments are committed together after
materialization, with the revision check inside one immediate writer transaction.
A concurrent capture rejects all fragments from the old read snapshot.

## Alternatives And Consequences

Rejected full-table hashing on every lookup, package-version repricing, caching
live status without its clock state, and reducing retained evidence. Warm controls
can reuse rendering without pretending that cold large ranges are constant time.
Large reports still include exact detail and incur HTML-transfer/paint costs.

## Guardrails

`test_dashboard_work_contract.py` checks pricing-cache replacement, version-neutral
accounting identity, rule invalidation, single-snapshot status, rendered section
reuse, missing-navigation recovery and exact primitive quota serialization.
Existing accounting, economics-oracle, snapshot-race and live-clock tests remain.
`benchmark_range_navigation.py` checks exact selected/historical/account/economics
hashes against release 2.12.0, with CPU and wall timings on disposable copies.

The unprofiled frozen-input comparison measured uncached Today/Yesterday/7-day
loads at 4.18/1.17/3.37 seconds versus 13.20/13.88/16.57 seconds for 2.12.0;
cached Today/Yesterday were 0.11/0.12 seconds versus 0.39/0.45 seconds. These
are local backend timings with the monetary index primed, not native paint
measurements or a promise for other machines. Private evidence stays ignored.
