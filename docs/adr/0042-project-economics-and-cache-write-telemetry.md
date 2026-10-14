# ADR 0042: Project Economics And Cache-Write Telemetry

## Status

Accepted for version 2.6.0 on 2026-09-08

## Context

Project and model totals correctly conserve the durable ledger, but token
volume is not a complexity measure. A meaningful workload comparison needs a
stable turn grain while preserving complete totals for records whose upstream
turn identifier is missing. Cache-write fields are similarly source telemetry:
an observed zero does not prove that a provider cache was not created.

## Decision

Project economics consume the report's already-valued, transition-attributed
ledger records. A project turn is one distinct `(project_key, task_id, turn_id)`
with a non-empty turn ID; a project-model turn additionally includes `model`.
Project totals remain inclusive of every positive ledger response, while turn
metrics expose response and token coverage for the non-empty-ID subset.

The all-project benchmark is weighted: its average cost per turn is the total
cost of fully priced project turns divided by their distinct count. It is never
the average of project averages. A turn containing unpriced usage remains
visible in token and response measures but is excluded from cost-based samples;
medians use the same fully priced turn population. These metrics describe
workload economics, not project quality or causal complexity.

Cache Write is displayed as **reported** telemetry. The ledger preserves source
values exactly, including zero. The renderer must not infer writes from input
and cache-read totals, backfill the ledger, or reduce pricing coverage merely
because every selected record reports zero.

## Rejected Alternatives

- Counting usage records as turns would inflate multi-response turns and make
  task/model comparisons dependent on parser cadence.
- Filling blank turn IDs from session or timestamp data would hide an upstream
  evidence gap and create unverified workload samples.
- Averaging project averages would overweight small projects.
- Inferring cache writes from uncached input would confuse ordinary input with
  a distinct provider-side event.

## Consequences And Guardrails

No schema, capture behavior, source scan, pricing pass, or public endpoint is
added. Economics aggregates must be built from the same valued record stream as
the report, preserve project/model token and cost conservation, retain stable
model ordering, and disclose coverage. Cached report HTML must be invalidated
when the shared renderer adopts these semantics. Focused tests cover mixed
models, transitions, roles, blank IDs, unpriced models, zero-cost records, and
the weighted benchmark.

## Per-Model Presentation Candidate: 2026-10-14

The primary within-project comparison exposes average API-equivalent cost per
response, responses per turn, compact tokens per turn and measured model turns.
Response cost averages use fully priced measured responses; turn cost averages
still use fully priced measured turns. A mixed-model turn participates once in
each model's population, so model turn counts must not be added to infer project
turns. These are observational workload measures, not controlled model-quality
or efficiency comparisons.

Keep totals, shares, exact values and denominators in secondary inspection.
Bound monetary display precision to suppress floating-point arithmetic noise,
while preserving meaningful tiny costs and exact source values in details.
The renderer consumes existing `ModelEconomics.metrics`; no schema, query,
repricing or population change is permitted. Require script-disabled browser
inventory evidence in the existing screenshot/allowance gate and owner UI review
before publication. Advance the existing HTML render revision so unchanged
ledger data cannot reuse the prior table; an upgrade regression requires a cold
new table followed by an identical warm cache hit. Technical verification does
not imply owner acceptance.
