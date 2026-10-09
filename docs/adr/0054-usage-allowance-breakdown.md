# ADR 0054: Usage And Allowance Breakdown

Status: Implementation candidate, 2026-10-09. Not a release decision.
Product direction: 2026-10-08.

## Context

The heatmap cannot explain composition. Quota is account-wide evidence, not an
additive allocation to projects. Allowance cost excludes included reviews;
dashboard API-equivalent valuation must not be replaced by that cost index.

## Decision

Compose already-valued trusted language summaries by local hour, project and
model. Preserve API unknown-price tokens, review tokens and known-zero credits
independently. Images retain their separate accounting section. Project
transitions and the global project selection apply only to usage, never meters.

Current cycle means the observed continuous suffix of one unambiguous active
weekly series with a fresh live anchor. Its opening is left-censored unless
captured continuity proves a boundary. Never derive it from deadline minus
duration. If unavailable, use the explicitly labeled dashboard selected range.
Daily full-range context and one local calendar day of detail share actual
UTC bounds; repeated hours retain offsets and skipped hours remain absent.
Captured meter points are not interpolated or connected across boundaries.

Prepare both range scopes once. Store compact metadata, per-day composition
and project-hour partitions in the existing disposable rendered report cache,
with distinct namespaced keys. No new ledger schema or raw valuation index.
Identity binds ledger/pricing/renderer/evidence revisions, timezone, transitions,
global project keys, range and selected cycle. Writes are revision-checked;
superseded or stale source generations cannot enter preparation. Warm controls
decode compact summaries and only the selected day/project partition, never
historical allowance reports, source records, prices or fits.
The host also invalidates presentation when probe freshness changes or a
captured deadline passes without capture. An older cached status cannot
invalidate navigation from a newer rendered revision during startup.

Script-free commands carry an exact server-issued action. The host requires
the current rendered navigation; the stateless server requires an issued scope
bound to the same trusted snapshot and live evidence state. Both reject extra
fields and unsupported dates, hours and projects; revision/expiry changes
invalidate issued actions. Top ten projects plus
Other preserve every underlying model total and inspectable detail row.

Percentage-point estimates are detail-only: require an existing calibrated
pace for the exact interval, a reference available no later than its captured
origin (interval end), complete local coverage, the same limit/duration series,
compatible continuous evidence, no full-meter/credit cutoff,
and matching known allowance cost. Otherwise report explicit unavailability.
They never allocate the captured meter or claim complete account coverage.
Capture-causal means evidence available at that captured origin, not a forecast
made at interval start. A current-window reference is a retrospective workload
fit available at the origin; a previous-window reference is labeled separately.
Future recovered evidence cannot calibrate an earlier origin. Raw reported
movement corrections are retained, never replaced with running maxima. Credit
balance changes may include purchases and never prove individual event debits.

## Alternatives And Consequences

Rejected a second pricing index and using allowance_event_costs as dashboard
dollars: both create accounting divergence. Rejected nominal weekly openings,
interpolated meters and exact project quota: the evidence cannot support them.
Partitioned disposable caches avoid schema migration but cold preparation and
compact full-range summary size must be measured. No capture/backfill occurs.

## Guardrails

Verify monetary parity, exact additive totals, free/unknown distinctions, DST,
continuity, strict command validation, stale generations and zero warm historical
work. Browser and isolated real VS Code command-link acceptance remain separate
gates. No version bump, publication, installation or live-state mutation.
