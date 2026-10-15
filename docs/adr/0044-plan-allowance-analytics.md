# ADR 0044: Observed Plan Allowance Analytics

Credit observations and the monetary fit's reported-full cutoff are defined in
[ADR 0049](0049-credit-balances-and-saturated-allowance-fits.md). Raw reset evidence
and quota pace retain this ADR's contracts.

## Status

Accepted for 2.8.0 on 2026-09-21; amended for 2.8.4 on 2026-09-24,
indexed report calculation on 2026-09-25, and visible reading freshness for
2.9.3 on 2026-09-29; amended for unknown plan identity on 2026-09-29
and observation-source clarity for 2.9.5 on 2026-09-30; amended for
conditional pace semantics on 2026-09-30 and accepted for release 2.10.0
on 2026-10-01 after director review and human release approval; amended for
observed-cycle pace in 2.10.1 and compact pace presentation in 2.10.2 on 2026-10-02; amended for
calibrated-cost pace on 2026-10-03 (reviewed candidate, release pending).

## Context

Quota percentages are account-wide meters, while the local ledger describes
observed workload. Neither a subscription price nor account lifetime tokens
establishes a fixed monetary entitlement. Historical quota windows can change
slots, durations, reset timestamps, and plan. The retained calibration research
is [2026-09-21-plan-allowance-calibration.md](../research/2026-09-21-plan-allowance-calibration.md).

## Decision

Every capture reads the official App Server `account/read`,
`account/rateLimits/read`, and `account/usage/read` methods through a short-lived
stdio RPC client. Initialization and metadata requests never start a model turn.
A shared total timeout bounds the probe. Failure is a content-free capture
diagnostic and does not fail ordinary usage capture. The selected CODEX_HOME is
passed explicitly. Retain only plan, bucket, slot, numeric usage/reset metadata,
reset-credit count, and lifetime-token coverage diagnostics. Never persist
account identity, authentication, prompts, response content, or raw RPC frames.
Executable selection uses the shared resolver recorded in
[ADR 0016](0016-register-imported-tasks-through-codex.md), including the current
nested macOS desktop layout and its legacy and PATH fallbacks.
Protocol reference: https://learn.chatgpt.com/docs/app-server.

Ledger schema 3 and parser cache schema 10 add quota tables without rebuilding
language/image usage or losing parser checkpoints. Existing databases receive
private SQLite backups before migration. Future token_count events contribute
allowlisted rate_limits metadata. Registered historical sources recover newest
first using complete files up to 128 KiB or at most 64 KiB from each endpoint.
Partial boundary lines are discarded. Each capture spends at most 8 MiB in the
existing coalesced heavy-I/O lane. Source fingerprints persist resume progress;
changed sources are reconsidered. Device/inode transitions also invalidate
recovery state. Unknown pre-parser identities are not treated as mismatches;
size/mtime and the open-file identity guards still protect endpoint reads. Repeated recovered states use compressed
unique timestamps and retain source provenance, allowing future analysis without
another source scan. Endpoint recovery is always disclosed as partial history.

Reset segmentation uses limit ID, plan, and reported duration; slot is metadata,
not identity. One-point decreases and unsupported decreases below five points
remain meter corrections. Supported boundaries are classified conservatively:
scheduled-compatible, banked-reset-compatible, global-reset-compatible, or
early/unknown. Classifications describe evidence, not proven causes. A plan
change invalidates continuity. Empty plan metadata means unknown, not a change.
Within each limit ID, derive plan identity from neighboring known observations:
leading/trailing unknown runs use their sole known endpoint; interspersed runs
use matching known endpoints. Runs between different known plans stay unknown
and separate from both known series because the change time is unproven. An
all-unknown series retains unknown identity. Report/window identity uses this
derived plan; raw points, empty plans, and provenance remain unchanged. Duration
buckets stay separate and slot moves do not split them. Same-timestamp conflicts
retain deterministic insertion precedence and ambiguity; explicit different
plans never merge. Reset/correction detection still runs across metadata gaps,
so genuine reset boundaries remain intact. Missing raw identity still blocks
High/Medium confidence; resolving continuity does not strengthen evidence.
No cost or percentage delta crosses a segment.
No weekly duration is hard-coded.

For each segment, fit the median cumulative priced ledger API-equivalent cost
per integer percentage bin against used percentage, with a free intercept.
The estimated full-allowance value is 100 times the positive slope. At least
five distinct observation times and bins are required. Confidence gates:

- High: completed; at least 50 percentage points and 10 bins; fully priced;
  R² >= 0.98; pairwise slope P90/P10 <= 1.15; no ambiguous reset boundary.
- Medium: completed; at least 20 percentage points and 5 bins; fully priced;
  R² >= 0.95; pairwise slope P90/P10 <= 1.35.
- Low/provisional: at least 10 percentage points and a valid positive fit,
  with weaker evidence or an ongoing window; never a qualified completed estimate.
- Otherwise: insufficient data with no monetary estimate. Unpriced intervals
  never produce a monetary estimate. Incomplete ledger coverage cannot qualify.

The summary shows the latest window's valid priced fit in the largest type.
An ongoing window is labeled **Current · provisional**, with its observed date
range. Series identity appears when multiple buckets are active or the headline
cannot be matched to one active bucket; the active bucket row already identifies
an unambiguous current series. The summary omits repeated provisional confidence
wording and retains High/Medium confidence on qualified current headlines. Fit
evidence stays in collapsed diagnostics. If the latest reset window lacks a
valid priced estimate, use the most recent earlier valid priced estimate only
when limit ID, plan, and duration all match. Label it **Previous window**, show
its observation dates and series identity, and retain its confidence. Never
present that value as current or borrow it from another series. If no such
estimate exists, show insufficient data. When the latest window becomes valid,
it takes over the headline. The summary contains one economic figure. Earlier
High/Medium windows with series identity, dates, and confidence remain in the
collapsed reset-window disclosure. Current windows have dashed detail styling.
Lifetime account usage is coverage context only, never a fit input. Provisional
estimates are workload-specific observations, not cash or contractual
entitlements.

The additive API-v1 capability is `plan-allowance`. Status includes plan, active
buckets/reset timing, probe timestamp/freshness/diagnostics, and recovery counts.
Active reset times use the report's configured timezone and show both its
abbreviation and UTC offset. The report passes the timezone already resolved
for its range through the shared HTML renderer, so native and VS Code reports
use the same formatting. The report cache already keys by timezone; changes to
the allowance markup also advance the report-render revision to invalidate old
cached HTML.
The shared script-free report places Plan Allowance after KPIs/notices and
before Project Economics. It remains account-wide under project/date filters
and exposes reset-window and capture details in Day/Night and narrow layouts.
Each active bucket's native meter depicts the remaining allowance. Its adjacent
copy continues to show both used and remaining percentages, while the accessible
label and value text describe the remaining percentage.
The meter also labels the reading as current, last known, or partially refreshed
and shows the successful observation's local date and time. A failed newest
probe keeps that last successful value visibly labeled as last known; when no
successful quota reading exists, the report shows an explicit empty state.
Capture does not infer a replacement percentage from token totals or synthesize
missing history. Renderer changes advance the report-render revision so cached
HTML receives the freshness label.
Probe timestamps, recovery counts, fit diagnostics, and allowance history stay
in one collapsed diagnostics disclosure. History presents raw-evidence-backed
observed periods, newest first, separately from the monetary fit windows.
Capture tables show at most the latest 100 points per period/fragment and disclose
the full count. The
economic summary is unframed and uses a subtle divider. Report interactions
derive data only from the ledger and never probe or open JSONLs.

### Period-First Display Contract (R)

**Problem:** monetary segmentation is conservative about meter drops, omits
some same-time conflicts, and the former history selected only valid priced fits.
Neither estimator windows nor valid-fit history is authority for subscription
period identity. Repeating them as reset rows overstated that authority.

**Decision:** build a separate `display_history` from the request-local
`AllowancePreparation.raw`, retaining distinct exact captures and all loaded
provenance. Period/uncertain rows reference capture indices and untouched fit
indices; codec validation requires exactly one owner for every capture and fit.
No raw schema, source reads, monetary segmentation, numeric fit, headline,
pace selection, confidence, or price facts change.

Compatible limit, plan and duration evidence defines display continuity. Slots
are transport metadata. Missing plans may resolve to compatible known endpoints,
but never bridge different known plans; plan changes apply across durations for
the same limit. Scheduled deadline crossings with an advanced deadline, and
banked reset-credit decreases, support separate periods, including early resets.
Exact reset timestamps are not identity. Material unsupported drops, deadline
rebases and conflicting readings start uncertain fragments; subsequent compatible
readings do not remove uncertainty without supported boundary/identity evidence.
Initial coverage is left-censored: no duration-subtracted or actual start is
invented. Only the exact active-series capture anchor can mark a period current.
Current membership is independent of fit confidence, known opening or reset
certainty. An anchored uncertain range remains a primary `Current · uncertain
boundary` row; a lone active anchor is a current observed point with opening
unobserved, never an inferred full-duration period. Other uncertain fragments
remain in the collapsed uncertain-reading group.
Unanchored open coverage is labeled last observed, not current or ended.
Unsupported boundaries end coherent observed coverage, labeled `Coverage ended`,
not a proven reset period.

Official display continuity advances only on already-loaded live-member
readings. Interleaved stale/conflicting task snapshots cannot rebase, consume
reset credits, introduce a plan change into, or fragment a compatible official
range. Task captures join such a range only when bracketing official captures
in the same coherent range corroborate their meter and available plan/reset/
credit metadata. No task extrapolation supplies a range opening from a lone
anchor. Task-only historical coverage remains available without asserting live
authority; disputed/interleaved or later task evidence remains globally
uncertain with exact captures, provenance and named evidence reasons. Membership
uses `AllowancePreparation.raw`'s existing live set; direct pure callers may
derive that membership from the supplied `Live probe` provenance label.

This distinction fixes two presentation-model errors: certainty had incorrectly
gated current membership, and a shared mixed-source cursor let stale task
readings fragment coherent official evidence. Neither changes monetary
segmentation, estimates, confidence, headline or pace. Fits remain independent
indices; any fit crossing the final display/authority ownership barriers appears
once in cross-boundary detail. No current/official classification promotes it.

Render at most 12 periods and one collapsed `Uncertain readings (N)` group
(N is its full distinct-capture count), with at most 12 uncertain fragments per
page. Private issued links reach every older page. Selecting one owner shows
its local observed dates, full counts, boundary reasons, at most 100 exact
captures and 12 independent fits per page. Raw plans, durations, reset credits
and provenance remain inspectable. Fit and capture pages reach the oldest
retained entries without emitting tables for every collapsed fragment.
Independent fits are nested details; fits spanning display
barriers appear once in uncertain/cross-boundary detail, never split, averaged,
summed, duplicated as period values, or promoted in confidence. Capture and fit
pages default newest first; an explicit oldest-first capture toggle resets its
capture page. Labels distinguish older/newer from earlier/later chronological
navigation. Every count has a supported inspection path in the companion.

**Rejected:** changing estimator segmentation to match display; deriving display
from fitted windows; silently joining uncertain suffixes under a shared deadline.
These either change monetary facts or hide unsupported evidence.

**Consequences and guardrails:** report revision 7 invalidates older derived
payloads; HTML revision 37 invalidates old presentation. Cache format 2 stores a
single canonical capture pool and window point indices, rather than serializing
raw dictionaries both in windows and `display_history`. Decode restores exact
window dictionaries with point objects shared with the display capture pool.
Format 1 wrapped reports and older unwrapped reports remain readable; invalid,
duplicate, out-of-range, boolean and multiply stored references are rejected.
A 12,000-capture payload guard requires exactly one serialized dictionary per
capture and bounds size relative to the former single-copy window format.
The existing cache key
couples report revision to historical fit reuse, so upgrading incurs one refit,
not repricing unchanged events. Warm report/HTML paths do not regroup, reload raw
evidence, refit or reprice. Synthetic ambiguity/identity/local-DST/rendering tests,
numerical parity, single-load and existing warm-cache tests guard the distinction.
Legacy payload rendering remains readable; newly materialized reports always use
the period-first contract. Full-dashboard human acceptance remains separate from
synthetic layout verification.

R layout qualification belongs to the mandatory allowance browser unit, not
conditionally skipped pytest cases. Named `period-history` and
`period-history-dense` scenarios cover Chromium, WebKit and Firefox, Day/Night,
and 1440/760/360px widths (36 added identities, 252 allowance identities total),
with production rendering, real private-host issued navigation, keyboard
disclosure, oldest period/fragment access, capture pagination/order, cross-fit
inspection, local DST evidence and screenshots. Missing R cases fail the
independent inventory; these identities augment all 216 previous cases.

### Private History Navigation

The first R renderer truncated history without an inspection path. Counts and
cached raw evidence were not access. The accepted fix is a hidden
`codexUsage.navigateAllowanceHistory` webview command over the existing
authenticated `/v1/report` transport's private `allowance_action` parameter, not
a new endpoint, public Companion RPC capability, palette command, or manifest
activation. Existing script-disabled CSP remains unchanged.

Scopes hash the local ledger identity, ledger/pricing/report/cache revisions,
coverage, exact active account buckets/series, probe freshness, timezone/theme,
range, projects and transition setting. Thus account-wide facts remain identical
across report filters, but private link tokens intentionally differ. State owns
independent period/uncertain page indices and one selected owner, fit page,
capture page and capture ordering. Only exact issued current-scope actions enter
through the extension. Host validation rejects bools, invalid types, unexpected
fields, wrong scopes/series, non-neighbor/unissued actions and invalid indices.
Issuance itself checks owner membership, visible page and page bounds.

Reuse the breakdown action-hash receipt contract and its 24-hour/256-scope
retention limits under a separate `allowance-issued:` prefix. Previously issued
actions in a different report scope produce typed scope expiry; absent/expired
receipts or crafted actions are ordinary invalid requests, never permission to
silently retry. The extension recovers once only for typed issued-scope expiry,
clearing transient commands but preserving global filters. Explicit Reload,
new evidence/revision or report identity clears local issued state.

History pages replace only a delimited history slot after the existing monetary,
speed and breakdown render/cache paths. A first inspection of a new page may
decode the already cached derived allowance report; it never loads raw evidence,
prepares account history, reads task sources, probes, refits or reprices. Page
HTML and compact navigation cache under the full scope/state key. Revisiting a
page or default warm view reads only that bounded frame, not the full allowance
payload. Revision-pinned writes prevent concurrent capture from publishing old
page/receipt state. Standalone HTML rendering supplies only an overview: private
pagination capabilities are issued exclusively by the companion report host.

Rejected alternatives: emitting all old capture tables behind native disclosures
(unbounded DOM), borrowing chart state (wrong domain/authority), and a public
history endpoint (unnecessary surface). Guardrails include complete multi-page
traversal, exact/shared codec ownership, scope/shape/range/expiry rejection,
no-work first-page/revisit tests, frontend validation/recovery and mandatory
three-engine UI replay. Human dashboard acceptance remains a separate gate.

Observation details distinguish **Live probe**, **Task snapshot**, and
**Recovered task snapshot** from the stored provenance, retaining all applicable
labels for deduplicated observations without multiplying their count. Missing
or unrecognized provenance is **Unknown source**, never inferred to be a live
probe. A task snapshot's timestamp is when its quota reading was recorded by
Codex, not when the collector polled. Concurrent task snapshots can disagree
by a percentage point; raw values remain unchanged and small decreases retain
the existing correction semantics. Source-column hover text explains the
distinction once per table without adding summary text or repeating long
descriptions in every row. Observation, probe-diagnostic, and
detail-reset times use the configured report timezone. Observation details show
seconds and milliseconds; hover metadata retains precise UTC timestamps or
reset Unix seconds. Table markup avoids redundant representations per cell.

## Indexed report calculation (2026-09-25)

Ledger schema 4 adds disposable event costs and an account-wide allowance
report cache. The full ledger estimator remains the oracle. On an uncached
view, only trusted events without a cost for the current pricing and index
revision are priced. The indexed path then accumulates those costs in the
same timestamp and source order as the full calculation and runs the same
window segmentation, regression, highlight, and history code. The resulting
report is keyed by ledger revision, pricing/index revision, and coverage state;
live probe status is read for each view. Date, project, timezone, and theme
filters do not change this account-wide result. Rendered HTML retains its
separate view-specific cache.

Append capture retains existing event IDs, so only new rows need pricing.
Replacement and normalized rebuild delete prior events, cascading deletion
of their costs. Superseded generations are excluded from accumulation.
Recovery, corrections, reset observations, and coverage changes advance the
ledger revision and rebuild the window result from indexed costs. A pricing
revision invalidates all event costs and the window result atomically. The
index revision must advance when the cost-index or derived grouping contract
changes. Unknown-plan grouping advances allowance index revision to 2 and HTML
render revision to 17; otherwise unchanged ledgers could reuse fragmented
windows or their previous-window headline. A read-only
view of a pre-migration ledger or a snapshot overtaken by capture uses the
full estimator. Tied quota observations now use timestamp then SQLite insertion
rowid during loading, and retain that order during deduplication; set iteration
had made reset segmentation vary by process. This can change historical window
boundaries and estimates where the ledger contains contradictory observations
at one timestamp and slot. The prior result had no stable value to preserve:
on a September 25 disposable ledger snapshot, v2.8.8 produced 184 or 185
windows under different Python hash seeds. The current headline estimate was
identical in those runs and with insertion ordering; older window details
differed. The explicit insertion rule makes subsequent cached results
reproducible without discarding any observation from storage.

From 2.9.5, an independent allowance-report revision also participates in the
window-cache identity. When the pricing identity is unchanged, report-revision
changes invalidate derived reports without deleting or repricing event costs. Cost-index revision
2 remains unchanged; allowance-report revision 1 and HTML-render revision 18
invalidate the old generic source labels. No schema migration is needed.
The existing pricing identity still includes the software release version, so
an upgrade can rebuild the cost index once even when rates have not changed.
Decoupling releases from pricing invalidation requires a separate pricing-cache
contract and is not part of this presentation patch.

The index is derived from normalized ledger rows. Report views never read
source JSONL files or invoke capture, though an uncached view may write the
derived SQLite caches. This keeps the ledger-only reporting contract.

## Conditional quota pace (2026-09-30)

Two independent wrapping rows under each active meter continue the captured
percentage conditionally. Recent is signed net movement over actual elapsed
time, within 60 minutes. Daily weights signed interval rates by the integral
of exponential time decay, with a provisional six-hour half-life, within 24
hours. Intervals assume uniformly spread movement. Keep both when they disagree.
Use actual endpoints, preserve equal readings at distinct times and negative
corrections, and show actual observed span. Gates remain three/five observation
times, 30 minutes/three hours minimum span and maximum adjacent gap, and two
signed endpoint percentage points. These settings favor understandable semantics;
the calibration lacks uncensored exhaustion outcomes and does not prove accuracy.

The existing dollar segmenter cannot own forecast eligibility: it intentionally
accepts small decreases as corrections before checking resets, derives identities
retrospectively, and drops conflicting same-time samples. Those behaviors were
reproduced in the [review](../research/2026-09-30-pace-forecast-review/README.md).
Changing that model would change historical dollar results. Instead, a separate
pure evidence contract filters to the exact live anchor before resolving plans
or checking continuity. It uses raw provenance membership, limit ID, compatible
plan and duration; slot is transport metadata. Known plan changes under the
same limit cut continuity even when only another duration bucket reports them. Contradictory usage, known plans,
reset credits, or materially different reset clocks at one instant cut continuity;
an ambiguous live endpoint refuses fitting. A coherent later suffix can recover.
Identical evidence is deduplicated, without averaging conflicting readings.

Forecast continuity gives crossed-and-advanced reset evidence, credit decreases,
and material deadline rebases precedence over small corrections. Differences
within 60 seconds alone are clock jitter. Known reset/credit metadata survives
missing intermediate fields until a boundary or plan change. That memory checks
continuity only: never fill in a missing live reset for projection. Historical
segmentation, dollars, meter semantics and capture scheduling remain unchanged.

Project from the exact captured timestamp/percentage, using the captured reset,
never an intercept or the time the view opens. Compare unrounded arithmetic;
round displayed exhaustion times to 15 minutes, mark results within 15 minutes
of reset as near reset, and display whole positive balances (less than 1% below
rounding). Configured local dates and zone offsets disambiguate midnight and DST.
Rates and diagnostics survive missing reset metadata but reset-relative promises
do not. A failed latest read suppresses both; partial reads use present buckets
only. Expire at 30 minutes after capture or the captured reset, and also at the
predicted exhaustion when it is at/before reset. Expiry is inclusive. Expired
rows await fresh capture; only a fresh captured 100% reading reports 100% used.
An already open script-free page retains its visible observation timestamp.

Use the existing quota load and disposable allowance-report cache, retaining
raw provenance enums separately from display labels. Account-wide fits are shared
across date/project/theme/timezone views. HTML identity includes each row's
clock-derived presentation state; reevaluating that state neither reloads quota
history nor refits nor moves the absolute prediction. Inject the rendering clock
for deterministic expiry checks. Allowance report revision 2 and HTML revision
19 invalidate derived presentation; event-cost index revision stays 2. The
release-version pricing coupling remains, including one-time upgrade repricing.
No new table, service, dependency, chart or capture mechanism is introduced.

Production fits use evidence available in the ledger snapshot. Parsed/recovered
points lack reconstructible historical first availability: timestamp-prefix tests
prove no future metadata influence, not strict historical availability. Live-only
replay requires an additional read-availability cutoff. Focused contract/cache
regressions guard boundary memory, conflicts, signed movement, exact anchors,
expiry, no view-triggered probes/source reads/allowance repricing/refitting, and
indexed/full equality. Synthetic browser checks guard disagreement, wrapping,
contrast and existing meter accessibility in Day/Night at 360px and wider.

## Pace cache and preparation revision (director review)

The initial candidate decoded the full historical allowance JSON before checking
for a warm HTML hit, and reconstructed the full causal prefix inside each fit.
Counters covering quota queries and pricing missed cache decoding; a small
synthetic history also failed to exercise the actual history-size cost. Warm
cache verification must cover bytes selected/decoded as well as computation.

Store a compact pace-state sibling in the existing disposable allowance-report
cache. Full and compact rows share ledger, pricing/index/report revision and
coverage identity and are written atomically. The compact key appends
`:pace-state`; obsolete variants are discarded together. Use it plus the current
injected-clock probe status before HTML lookup; load historical windows only
when an HTML view must be rendered. Missing compact state is a cold lookup;
a pre-migration database retains the safe full-estimator fallback. Reject SQL
JSON extraction from the full payload: it would still read/parse history. No
new persistent table or schema migration is needed. Report revision 3 and HTML
revision 20 invalidate the initial candidate's cache; cost index stays 2.

`PreparedPaceEvidence` owns revision-scoped causal continuity checkpoints and
binary-searchable actual observations. Build it once from already-loaded raw
quota evidence for the active series; include limit-wide plan events from other
durations. Each checkpoint reflects only its observation-time prefix. Resolve
leading unknown identity at its first known endpoint by replaying that leading
run once at that origin, preserving earlier origins' unknown checkpoints. Known
plan changes end the current suffix; missing reset/credit memory, conflicts and
boundary evidence survive outside the fit lookback. Fitting accepts prepared
evidence only and selects actual points within 24 hours by indexed boundaries,
then applies the unchanged Recent/Daily gates. Never trim away continuity memory
at an arbitrary lookback cutoff or resolve identities using future metadata.

Preparation remains linear/full-history work on each newly materialized report
revision, shared by its active buckets. It is not a durable incremental index:
recovery or source replacement may alter old evidence. Warm cached views reuse
rates and checkpoints are not rebuilt. Selection/fitting is bounded by observed
time, not by an invented sample-count cap. Separate loading, preparation,
selection/fitting, historical cache decoding and repricing in benchmarks. New
revision materialization and uncached history rendering still have measurable
costs; the under-20ms fit target is not an end-to-end report latency claim.

Guardrails compare prepared origins with the frozen full-prefix oracle, forbid
prefix iteration/preparation during fits, and trace compact-only cache SQL plus
small decoding on warm HTML hits. Large synthetic benchmarks cover two active
buckets and full monetary equality. Keep raw private snapshot evidence ignored.

## Observed-Cycle Pace (2026-10-02)

Add one Cycle row after Recent and Daily. Its baseline is signed net percentage
movement divided by actual elapsed time between the first and exact live last
observation in the current coherent suffix. Include idle time and retain small
negative corrections. Do not weight intervals, assume an initial 0%, subtract a
nominal duration from the reset clock, or borrow a previous window. Show the
actual span, including days. A left-censored suffix means the reset start was
not observed; an unknown boundary remains unknown, not a claimed global reset.

Reuse the existing causal continuity contract and exact live-anchor membership.
After a supported reset, plan change or conflict, start at the actual first
post-boundary observation, even if it already reports nonzero usage. Cycle uses
the Recent minimum of three distinct observation times, 30 minutes and two
signed endpoint percentage points. These are cautious availability settings,
not accuracy guarantees. Unlike the interval-weighted Daily calculation, an
endpoint baseline needs no assumption about movement within a gap: include the
gap's elapsed time rather than rejecting it. Keep the maximum gap, corrections,
boundary and uncertain reset origin in collapsed diagnostics. An unobserved
reset within a gap can still make the baseline misleading.

Preparation adds cumulative maximum-gap and correction summaries to each causal
checkpoint in the existing pass. Cycle reads indexed endpoints and summaries;
it never slices or walks the entire cycle during fitting. New revisions still
prepare full history. Reuse the same disposable compact cache, capture anchoring,
local-time projection and expiry contract. Recent/Daily outputs, dollar fits,
raw points, provenance, probes and capture scheduling remain unchanged. Report
revision 4 and HTML revision 21 invalidate old two-row payloads; the event-cost
index remains revision 2. Tests guard multi-day spans, signed endpoints, gaps,
reset memory, conflicts, causal origins and endpoint-only reads on 52,000 points.

## Compact Pace Presentation (2026-10-02)

Repeated forecast prose and hour-only reset gaps impede scanning. Label rows
Recent, Daily and Cycle average with their actual observed spans. Shorten the
conditional outcome to "Estimated to run out" or the remaining percentage.
Round displayed reset gaps to approximate whole hours (days/hours after 24h),
retaining minutes below one hour. Comparisons still use unrounded predictions.

Use today/tomorrow relative to the report render clock's local calendar date,
not the captured anchor date. Later forecasts retain a calendar date. Preserve
the existing 15-minute forecast display rounding, and keep full local dates and
UTC offsets in semantic time metadata and hover text to disambiguate DST hours.
Observed spans, methods and evidence remain available in collapsed diagnostics.

Include the local render date in HTML cache identity when pace rows are present,
so a fresh reading cannot reuse yesterday's relative-day label across midnight.
Do not refit, reprice or recapture for this presentation transition. HTML revision
22 invalidates old copy; allowance report revision 4 and cost index revision 2
remain unchanged. Warm compact-cache behavior and all mathematical, causal and
expiry contracts stay intact. Tests cover midnight caching, DST, escaping and
unchanged forecast data.

## Calibrated-Cost Pace (2026-10-03)

Quota movement below two net percentage points made the direct-meter method
unavailable even when captured priced consumption was increasing. The estimator
input contract caused the missing rates; capture and pricing were functioning.
The approved [calibrated-cost revision](../plans/plan-allowance-pace-forecasts.md#calibrated-cost-revision-proposed-2026-10-03)
supersedes the earlier quota-only input restriction and Daily weighting above.

Recent (up to one hour), Daily (up to 24 hours), and observed Cycle now prefer
`100 * period API-equivalent cost / reference full-allowance value / observed hours`.
Use the latest usable priced finite-positive current-cycle estimate, otherwise
the latest compatible earlier estimate, including Low/provisional. Compatibility
requires the causal known plan, limit ID and duration, never slot. All three
periods select one reference together. Do not average values, freeze a previous
reference after a current estimate exists, borrow another bucket, or require
High/Medium qualification. Missing plan identity cannot borrow a known plan;
the latest causal limit-wide plan event may resolve missing live metadata,
including an event from another duration bucket. Conflicting known plans at the
same latest timestamp leave calibrated identity unavailable. This reference
identity does not change direct-meter continuity or monetary segmentation.

Reference fitting filters observations after the exact live anchor before
identity resolution and segmentation. Production uses the current ledger
snapshot; strict historical accuracy replay also needs reconstructible first
availability. Without it, captured-data comparisons are retrospective. Monetary
windows remain retrospective and unchanged. A cold historical origin may require
a separate causal prefix fit; normal current snapshots reuse prepared windows.

Use shared trusted language-cost prefixes, excluding the left endpoint and
including the anchor timestamp. Every interval uses actual observed quota
endpoints within the coherent suffix; idle time counts. Do not invent a reset
origin or lookback endpoint. Cost arithmetic has no quota-movement, sample-count,
minimum-span or gap gate beyond a positive observed interval and coherent exact
anchor. Zero fully priced cost is a valid zero observed rate: there is no
exhaustion time, and remaining quota stays unchanged at reset. Unpriced events,
incomplete local capture coverage, unavailable references and invalid intervals
try the direct-meter fallback; missing evidence is never zero consumption.

Raw full-meter evidence cuts off calibrated consumption through subsequent small
corrections and conflicts until a reset or plan boundary establishes a new
suffix. Preserve ADR 0049's monetary cutoff, complete raw evidence and direct
meter semantics. Do not include preceding credit-funded or post-full cost in a
resumed cycle. Keep freshness, expiry, unrounded reset comparisons, local times
and exact captured percentage/reset anchoring.

The direct-meter fallback retains its existing evidence gates and signed
corrections. Daily is now plain net movement divided by observed hours, matching
the calibrated period's elapsed-average meaning. Six-hour weighting is rejected
because method switching must not change what Daily means. Cost rows carry an
estimated label; method, cost, reference identity/value/dates, coverage and
limiting reasons remain in the existing folded diagnostics. No new UI group,
collection schedule, pricing rate, credit or image forecast is introduced.

Report revision 6 and HTML revision 24 replace derived payloads atomically;
schema 5 and cost-index revision 2 stay unchanged. Warm HTML hits decode compact
pace state only, without historical payloads, cost scans, fitting, source reads,
repricing, capture or probes. Reference indexes are prepared once per origin;
three bounded prefix differences supply each active bucket's periods.

Guardrails cover hand arithmetic, flat meters, zero/unpriced/incomplete evidence,
current/previous switching, multiple buckets and slots, causal future rejection,
reset clipping, actual spans, saturation/corrections, fallback Daily semantics,
full/indexed parity and exact monetary-output preservation. Counter assertions
protect warm behavior; separate measured cold/warm/quota/event-update benchmarks
avoid timing gates. This empirical conversion remains workload-specific and
cannot establish contractual entitlement, complete account-wide coverage or
validated exhaustion accuracy. These limits are diagnostics, not a confidence
threshold that hides calculable rates.

## Rejected Alternatives

- Dividing cumulative lifetime dollars by current usage crosses resets and
  produces misleading values.
- Treating slot or exact reset timestamp as identity creates false windows when
  producers move slots or adjust clocks.
- Scanning historical file interiors creates unbounded capture latency.
- Reusing account identity to reconcile devices adds sensitive retention without
  proving local coverage.
- Inferring entitlement changes from fitted values confuses workload/pricing
  changes with upstream policy.

## Consequences and Guardrails

Local estimates remain workload-specific and may omit usage on other devices.
No UI claims cash value, contractual entitlement, or changes to OpenAI limits.
Oracle tests enforce segmentation, pricing, confidence, and no cross-window
consumption, unknown-plan bridges, explicit plan changes, real resets around
metadata gaps, and genuine insufficient-window fallback; migration tests preserve
usage; report tests forbid source reads and probes. Quota storage is independent of language and image accounting.
