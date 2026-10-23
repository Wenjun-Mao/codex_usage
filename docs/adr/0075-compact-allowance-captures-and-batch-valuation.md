# ADR 0075: Compact Allowance Captures And Batch Valuation

Date: 2026-10-22. Status: locally implemented and verified; unreleased.

## Problem

After ADR 0074, Today still serializes hundreds of thousands of canonical
capture dictionaries. Repeating their field names enlarges the persisted report.
Thirty-day valuation binds the same immutable pricing schedules for each event;
turn calculations aggregate token and credit components that their metrics do
not consume. These costs remain above the 3s/5s preparation targets.

## Decision

Use allowance reference format 3 with ordered field layouts and capture rows
`[layout_index, ...values]`. Preserve dictionary insertion order, JSON numeric
types and negative zero on reconstruction. Keep order-insensitive, type-sensitive
duplicate detection, exact capture/fit ownership and all reference validation.
Layouts require unique string fields; row length and integer layout references
are checked before reconstruction. Nested legacy values retain JSON comparison.
Format 1, format 2 and unwrapped legacy reports remain readable. The cache format
revision selects a new key; existing readers never decode format 3 under a
format 2 key. Canonical ledger/parser formats and accounting identities do not
change.

A codec rollover may rebuild allowance data while base HTML remains cached.
The base renderer must hand that prepared report to history rendering even on
its HTML cache-hit branch: the shared read snapshot cannot see cache rows just
published by another connection. An end-to-end format 2 -> 3 test forbids
revaluation of the cached range and verifies fresh issued navigation.

Bind immutable API and credit schedules once per `value_records` call. Resolve
each response against its own timestamp, model alias and request context tier.
Keep the original arithmetic functions shared with scalar valuation. Resolvers
and per-model timeline lookups are request-local; replacing either schedule
affects the next call. There is no retained event-value cache.

For turn metrics accumulate only total USD and unpriced tokens, preserving the
first response as the seed and sequential additions within each turn. Retain
first-seen turn order and Python's builtin `sum` for final priced-turn and
priced-response populations. Keep full ordered component totals separately for
project/model summaries. Project/task/turn/model identities, blank IDs, mixed
priced/unpriced turns and response populations are unchanged.

## Alternatives And Consequences

Skipping validation or using a trusted fast codec would weaken cache corruption
guards. Replacing sequential additions with compensated sums would change exact
accounting. Persistent priced-event partitions need a separate invalidation and
retention proof and are not introduced here.

The compact format creates temporary row lists and identity sets; measure peak
memory and first-fill cost alongside payload bytes and full report times.
Measure complete HTML/CSV equality, not just faster encoding. Focused tests cover
legacy formats, malformed layouts, numeric identity, effective-date boundaries,
schedule replacement and adversarial floating additions. Broad accounting and
range verification remains required. Local qualification does not publish or
install a release.

Ten matched pairs measured first 30 days 8.96 -> 8.06s and post-append Today
8.27 -> 8.12s. Cache payload fell 40.7%, but encoding CPU did not improve;
publication and detail decoding are cheaper. Both 3s/5s targets remain unmet.
See [qualification evidence](../research/2026-10-22-serialization-and-valuation.md)
for exact output comparisons, first-fill/storage trade-offs and phase limits.
