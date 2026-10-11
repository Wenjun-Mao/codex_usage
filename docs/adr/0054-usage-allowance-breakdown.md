# ADR 0054: Usage And Allowance Breakdown

Status: Accepted after full-dashboard owner review, 2026-10-10.
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

The dashboard calendar Range is the sole date-range authority. Continuity
fragments are evidence, never primary navigation or nominal reset cycles.
Time / Projects shares one chart area. Time offers Daily / Hourly, metric,
Model / Project stacks and one Weekly allowance / Credit balance / None overlay.
Default is API cost, model stacks, weekly overlay; Today/Yesterday use Hourly,
wider ranges Daily. Grain persists within a scope; a new range resets defaults.

Daily spans every selected calendar date, including unobserved/empty/future dates.
Hourly is bounded to seven consecutive local dates, initially ending on the latest
in-range usage or account capture. Previous/Next/Latest move bounded seven-day
windows. Daily drill selects a day and opens its hourly window; Daily return
clears dependent detail and restores the entire range. Project drills filter
usage detail only and never mutate global filters or account overlays.
Project drills are issued only for projects present in the selected calendar
summary. Historical-only projects remain in capture-causal exact evidence as
plain labels marked "No selected-range usage", without calendar drill commands.
An evidence inspection never widens the calendar range to make a project valid.
Projects shows ranked top ten plus inspectable Other, stacked by model; no account
axis against categories. Explicit metric changes never change the overlay.

One UTC transform positions usage bars, captured account points and sparse local
time ticks. Left axis is zero-based selected metric; right is account-wide weekly
0-100% or finite observed credit range, explicitly not zero-based. None removes
the right axis. Stacks and compact account dots have separate visible keys.
Capture points never interpolate or connect across any boundary. Multiple supported
weekly limit/plan identities stay separate; conflicting/unsupported readings
are disclosed, not manufactured into a meter. Stale latest probes do not hide history.

`BreakdownInterval` names two distinct membership contracts. Selected range
retains dashboard calendar `[start, end)` accounting. Retained continuity intervals and their
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

The weekly overlay is account-wide historical known-weekly readings, with a
visible limit/plan legend and a fixed percentage axis. Nonweekly and missing-duration evidence stays in
the exact-reading disclosure, never silently presented as weekly. A domain
without weekly readings explicitly marks weekly allowance unavailable.

Prepare selected calendar composition per range; share account-wide evidence
across ranges and project selections. Prepare exact retained weekly composition
only on an issued interval inspection, then reuse it across calendar ranges.
Store compact metadata, per-day composition and project-hour partitions in the
existing disposable rendered report cache. [ADR 0055](0055-range-independent-breakdown-preparation.md)
defines the separate account, selected-range and historical cache identities.
No new ledger schema or raw valuation index. Renderer/state revision 6 excludes
earlier eager-preparation caches; exact old issued receipts can classify
expiry but cannot reinterpret old fragments as a calendar range. Writes are revision-checked;
superseded or stale source generations cannot enter preparation. Warm controls
decode one selected summary and at most seven per-day/project composition
partitions for Hourly. Daily uses prepared model/project stacks and project-model
summaries, not every project-hour partition. They never load historical allowance
reports, source records, prices or fits or prepare continuity.
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
Collapsed evidence entries carry plan/limit/boundary context and issued exact
interval inspection. Freshness never replaces the selected calendar range. Bounds are observed endpoints,
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

Cold preparation reuses calendar selection valuation without querying historical
usage outside that selection. The earlier missing-union eager strategy is
superseded by ADR 0055: a retained interval is queried/valued only when its exact
inspection is opened, using timestamp-indexed capture-causal bounds and the same
trusted-record decoding, project aliases and transitions. Selected All-time still
uses its already-valued baseline. Partition account evidence and balances once
per account identity, so warm windows/metrics/groups/days/drills never load
historical reports or prepare continuity/deltas/fits/prices.
The scope directory stores bounds and partition identities only; warm rendering
reads the selected calendar summary, not every historical composition. An explicit
continuity inspection prepares or reads only its named capture-causal summary.
Revision and issued-scope expiry/recovery rules remain unchanged. Reject silent date-only
identities, reset-zeroed balances and inferred credit deductions.

Credit balance points label an observed-range scale. The original exact Decimal
balance/change table is available through issued per-local-day inspection, including
spanning intervals. No separate net-change plot or inferred hourly debit remains.

Visible labels use metric-aware K/M/B/T units and readable dollars, ordinarily two
decimals, never general scientific notation. Tiny values increase precision; long
axis values use a named common scale, and collapsed large-balance movement uses an
explicit exact common offset. Rounded tick ceilings contain unmodified bar values.
Full numeric values/timestamps remain in exact inspection and accessible mark names.
Responsive gutters and wrapped offsets keep both axes visible without font shrinking.

Cold preparation retains every raw quota identity (timestamp, limit, slot, plan,
duration, used, reset, credits and provenance) and original balance adjacency.
Derived per-day displays keep actual bucket endpoints/extrema and both sides of
continuity boundaries/conflicts. Shared display reduction keeps up to four actual
points per 180 time bins per series, plus all boundaries; boundaries are exempt
from the ordinary budget, never silently dropped to meet a hard cap. Adversarial
boundary-heavy evidence can therefore exceed this budget, an explicit residual risk.
Warm reduction works on annotated display partitions and does not recompute
continuity. Exact issued day inspection loads the raw selected-day partition only,
never serializes all retained raw readings in the All-time default.

## Account Overlay Readability (2026-10-10)

Dense retained readings must not look like extra model series. The primary account
series uses neutral text color, compact dots and an explicit right-axis label;
additional account identities have separately keyed colors. Only the latest
captured point per account identity is enlarged, and its value/timestamp appears
in the account key. Usage colors are keyed immediately above the bars. Dense
boundary diagnostics belong in account evidence disclosure, not the primary key.
These are unconnected actual readings, not interpolated allowance curves. All
retained boundary points and exact-day inspection remain unchanged; presentation
must never manufacture reset annotations or hide conflicts to simplify the plot.

The owner selected Axis-Linked over vertically aligned panes on 2026-10-10.
Usage key and metric title align left; the neutral account key aligns right above
its percentage/balance axis. The single-series weekly key is compact: Allowance
Remaining, then Latest and the most recent captured in-range percentage. Account
scope, limit/plan and timestamp belong in tooltip/accessibility and exact evidence;
multiple identities remain visibly distinct. Balance scale offsets and conflict
warnings remain explicit. No alternate pane runtime path is retained.

Bars occupy half their time slot and stay centered on the same UTC transform.
Below-resolution nonzero components use understated colored ticks at their true
stack boundary, not open circles resembling separate point annotations. Segment
values and additive geometry are never inflated to create minimum-height bars.
Exact values remain in mark titles and issued inspection. These readability
changes do not change valuation, capture coverage or account attribution.

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
