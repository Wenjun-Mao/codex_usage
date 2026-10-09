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

`BreakdownInterval` names two distinct membership contracts. Selected range
retains dashboard calendar `[start, end)` accounting. Current cycle and its
hour/day partitions use allowance's capture-causal `(origin, capture]`: exclude
the opening event, include the captured endpoint, and assign an exact hour/day
boundary event to the interval it closes. Integer-microsecond SQL inclusion
padding is private to query bounds, never the displayed/calibration endpoints.
Calendar rows cannot borrow a right-closed calibration merely because their
scalar costs happen to match. They disclose this incompatibility explicitly.

Sparse fixed-font HTML time ticks share the actual UTC geometry of daily,
hourly and meter charts; narrow displays hide secondary ticks, not axes.
Repeated/partial hours retain chronological keys and visible offsets. Complete
day/hour command lists are disclosures, not substitutes for aligned axes.
Bucket hover/accessibility names include date/time, project/model context and
value. Visible bounds omit implementation microsecond padding; exact raw rows
remain inspectable. Scope/accounting explanations are progressive disclosures.

The meter is weekly and account-wide: current cycle plots the exact active
limit/plan; Selected range plots historical known-weekly readings, with a
visible limit/plan legend. Nonweekly and missing-duration evidence stays in
the exact-reading disclosure, never silently presented as weekly. A domain
without weekly readings explicitly marks weekly allowance unavailable.

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

The server separately records issued actions, validating their exact shape
before any expiry recovery. A genuinely issued but expired snapshot/evidence
scope returns HTTP 409 `breakdown_scope_expired`; malformed, altered and
unissued inputs remain HTTP 400. Host invalidation compares issued evidence
state independently of the target basis. For backend-resolved calendar,
timezone, transition or evidence expiry, only this typed response permits one
bare-report retry, clearing both chart scopes while retaining global filters.
There is no retry for arbitrary 400s or unrelated conflicts. Older cached
status must not invalidate a newer rendered revision.

Receipt hashes have their own bounded disposable policy in the existing
rendered-report table: the `breakdown-issued:` namespace survives ordinary
older-generation report pruning, but retains at most 256 scopes for 24 hours.
Only exact canonical action hashes are retained, not report bodies or bearer
credentials. Receipts authorize only typed-expiry classification, never stale
data resurrection. Expired/evicted receipts are hard rejected; explicit Reload
clears chart commands and works without any receipt. No schema migration.

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
