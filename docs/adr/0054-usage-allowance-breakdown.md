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
Calendar navigation retains full range bounds but initially opens the latest
in-range usage or raw account-wide quota/balance capture day, not the calendar
endpoint. Empty ranges use the clock day clamped to their bounds. Historical
endpoints are actual captures; a singleton at midnight stays on its capture day.

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

Prepare selected range and all retained observed weekly scopes once. Store compact metadata, per-day composition
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

## Unpublished Extension Contract (2026-10-09)

Reuse the prepared capture-causal continuity checkpoints to enumerate every
retained weekly portion, including ambiguous/unknown-plan portions. Stable IDs
bind limit, observed opening and boundary identity, never labels or array order.
Dated entries carry plan/limit/boundary context. Current freshness controls only
the current alias/default, not historical access. Bounds are observed endpoints,
not nominal openings or a claim of whole-window coverage. Preserve raw conflicts.

Estimated credits use already-valued Standard credits in all composition paths;
included usage has an estimate too. Known free zero and unknown values remain
distinct. This is neither observed billing nor per-project funding attribution.

Prepare account-wide balance evidence from the entire retained quota-read
sequence, not the bounded heading-history disclosure. Missing-read placeholders,
invalid metadata, unlimited balances, nonchronological timestamps and unknown or
changed plans interrupt adjacent delta continuity. Use exact Decimal text and
original endpoint timestamps. Quota resets do not interrupt balance continuity.
Net decreases and possible reload/grant/refund/adjustment increases are separate
labels; neither proves event-level funding. Intervals crossing selected day or
window boundaries stay visible with exact original endpoints and an unallocatable
boundary-crossing label, never prorated or assigned to a bucket. No historical
credit backfill, source capture, extra Plan Allowance line or depletion forecast.

Cold preparation reuses calendar selection valuation, then queries/values only
the missing union of observed weekly intervals through the ledger timestamp
index. Each required event is valued at most once; years before the first weekly
evidence and inter-window gaps are not decoded/repriced merely for Today.
Selected all-time may reuse its complete already-valued baseline. The finite
`bounds_union` query contract intersects existing bounds and preserves canonical
trusted-record decoding/order, project aliases and transitions. Timestamp
slicing prevents window x records valuation. Partition balances by
intersecting local day once, so warm windows/metrics/groups/days/drills never
load historical reports or prepare continuity/deltas/fits/prices.
The scope directory stores bounds and partition identities only; warm rendering
reads one active-window composition summary, not every historical composition.
The current alias reuses its matching observed-window composition partition.
Revision and issued-scope expiry/recovery rules remain unchanged. Reject silent date-only
identities, reset-zeroed balances and inferred credit deductions.

Balance plots label their observed-range (not zero-based) scale; a separate
compact signed net-change axis places each original interval at its exact delta
magnitude. Neither connects balance points nor divides an interval into hours.
Missing in-domain captures and spanning evidence are distinct states. Chronology
compares parsed instants, not ISO text, retaining original offsets in exact rows.

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
