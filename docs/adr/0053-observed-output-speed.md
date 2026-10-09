# ADR 0053: Observed Output Speed

Status: Accepted for the implementation candidate, 2026-10-08.

## Context

Language deltas are durable but are not response timers. The exploratory probe
showed measurable local output envelopes as well as ambiguous pairing, collapsed
timing and replayed identities. Treating capture duration as generation duration,
or resolving duplicate IDs by arrival order, would manufacture speed samples.

## Decision

One observation joins a response usage record to the following emitted language
ordinal within its verified source generation. All six token fields, exact model,
turn and ordered timestamps must agree. Its numerator is output tokens, already
including reasoning once. Its denominator runs from the first valid model item
start to the last model item or generated output end. Counted reasoning requires
reasoning timing. Missing, negative, overlapping, collapsed, sub-resolution,
aborted, mixed and ambiguous boundaries are excluded, never clipped or repaired.
Legacy or mismatched-version timing checkpoints begin unsafe. Timing state is bounded and content-free;
streamed payloads supply structural header metadata only.

Complete bounded structural extraction crosses ignored output/media strings,
including required metadata after content. A prefix alone is not evidence of
absence. Known payload rows can checkpoint mid-row and resume within the shared
byte budget; checkpoints contain lexer grammar position and headers, never text
or media. Invalid UTF-8/JSON, duplicate required keys, excessive nesting (64), or
oversized required headers (256 decoded characters) invalidate the affected
response boundary rather than silently truncating evidence. Unknown/unclassified
financial rows still require exact parsing and can be terminally unsupported at
the recovery byte limit. Long valid output is not excluded by length alone.
Structural-first draining applies only to message/reasoning bodies. Tool calls
and results retain the existing Unicode/escape-sensitive full extraction route
for precise image parameters, reference kind, result usage and repository-path
evidence. Timing projects separately and never lowers accounting precision.

Durable tool intervals and output instants can revoke already-promoted samples,
including evidence arriving after token_count or a restart.
Untimed actual tool/unknown-item evidence is attributed to its turn and excludes
that turn only; item existence is not execution. Plan/UserMessage/HookPrompt,
SubAgentActivity and review-mode bookkeeping are not tool intervals. Extension
items can represent execution: valid intervals exclude overlap; untimed evidence
excludes only its attributable turn, as for other unknown execution variants.
There is no source-wide unknown-tool sentinel. Response identities
settle as groups: equivalent copies contribute once, conflicting copies all
exclude. Superseded source generations do not participate. No foreign key points
to a normalized event ID; report joins use generation plus emitted ordinal so
ownership rebuilds cannot orphan timing. Missing source files retain accepted
facts, while unrecoverable remaining history receives a terminal reason.

Cache schema 10 to 11 and ledger schema 5 to 6 are additive, with private backups;
parser version remains 8. Normal capture observes new timing in its existing
parse. Historical timing shares the four existing recovery slots with images,
receives at least one slot, prefers recent unserved sources and rotates served
sources fairly. New arrivals enter behind already-waiting recovery. Byte-limited
guarded slices checkpoint independently without inserting language deltas.
Staged replacement promotes timing with the corresponding parser workset.
Both historical domains enforce strict row budgets. An image slot attempts at
most one parse and 128 unavailable metadata candidates; failures cannot consume
another source's parser slice. Normal tail-capture limits remain unchanged.

Speed has its own revision, metric version and aggregate/render caches. Reports
read only the ledger and reuse a separately cached monetary report within one
shared read snapshot. Timing-only rows never enter the monetary/image parser.
Speed-only
recovery does not invalidate monetary valuations or allowance fits. Aggregates
are medians of response facts, never means of bucket or project medians; project
transitions precede selection. Hours preserve UTC offsets through DST. Hourly
navigation uses explicit seven-local-day windows without changing global filters
or all-range summaries. Empty selection is genuinely All Projects, while an
explicit selection of all existing keys remains a fixed subset.
Saved windows carry their prior range scope: a local-midnight rollover clamps
them to the new range, while direct out-of-range and stale host commands reject.

### Responsive Calendar Presentation (2026-10-08)

The original fixed-width SVG scrolled its y axis out of view and appended a
final date beside an already adjacent tick. Hourly's remembered seven-day window
also lacked context for the full selected range. Replace this geometry at the
renderer, not by shrinking fonts or changing range/metric semantics. Daily fits
the entire selection. Hourly retains seven local dates, a full-range daily
overview with calendar-date selection shading, explicit detail/total-day counts,
and an allowlisted Latest week command. Empty detail retains a populated overview
when other dates have evidence. Account-wide recovery progress is visibly scoped
as such; it is not filtered-project coverage.

Axes stay within the container without horizontal scrolling. Constant-size HTML
labels use container-width tick sets, mandatory endpoints and collision spacing;
SVG positions remain proportional while marks and interval strokes keep fixed
dimensions. Fixed plot padding and visible SVG overflow keep endpoint markers
and their keyboard-focus strokes inside the parent at narrow widths.
Preserve medians, middle-50% intervals, small samples, missing gaps,
exact keyboard-accessible details and script-disabled CSP. Rendering revision 28
invalidates old HTML; no new scripts or dependencies are introduced.

Hourly aggregation and calendar enumeration share a nominal local-clock-hour
identity with the observed fixed UTC offset. Rounding with a ZoneInfo object can
re-resolve the offset inside a partially skipped/repeated hour; stepping UTC
hours from midnight can instead produce half-hour-shifted labels. Enumerate valid
local hour boundaries/folds, including partial hours, preserve their actual
offsets, and order by UTC instant. Timing-query revision 2 invalidates old
aggregates without changing accepted facts, accounting, recovery or schemas.
Guardrails cover Toronto, Lord Howe and Chatham transition calendars and actual
aggregate/calendar joins, plus rendered tick bounds, embedded narrow containers,
single days, empty historical windows and native Latest week navigation.

The initial usability defaults are 10 ms minimum model-item duration and 500
output tokens, with sensitivity checked at 50/100 ms and 100/2,000 tokens. Fewer
than five responses shows no number; 5-19 is marked small sample. Median, middle
50% variation, responses and distinct tasks/sources remain inspectable. This is
client-observed output-phase speed, not server decode speed or causal evidence
of a subscription rollout. Efforts are pooled, not declared irrelevant.

## Alternatives And Guardrails

Rejected: report-triggered JSONL scans, another collector/budget, global parser
cache resets, event-ID binding, first-wins deduplication, interpolated gaps,
effort-split defaults, inferred service tiers and permissive webview scripts.
Host commands remain allowlisted with exact argument-shape, scope, calendar-date
and neighbor/latest-window validation. Mismatched collectors fail visibly.

Native acceptance uses disposable profiles and the supported
`--use-inmemory-secretstorage` flag: a temporary HOME alone does not isolate
Electron's native credential backend on macOS. It explicitly attaches the
separate webview iframe target, reads rendered DOM, and dispatches real mouse
input; no product scripts/CSP change or host-only navigation substitutes for
click acceptance. Evidence records harness/source and bundled-collector hashes.
Rendered-click acceptance must clear the variable-height sticky toolbar with
real scrolling and hit-test the target link before dispatch; a DOM-visible
quad alone does not prove an unoccluded clickable control.

Synthetic replay covers checkpoint boundaries, late revocation, order-independent
conflicts, additive migration, replacement, retention, transitions, DST, display
gates and zero warm timing/monetary work. Packaged tests exercise migration and
recovery in disposable homes. Private replay inputs and outputs are never public
fixtures. See [the approved plan](../plans/2.11.0-observed-model-speed.md) for the
candidate and release gates. This ADR complements [0002](0002-native-html-svg-dashboard.md),
[0022](0022-guarded-append-parser-checkpoints.md),
[0033](0033-persistent-collector-and-durable-ledger.md),
[0043](0043-image-generation-accounting.md), and
[0045](0045-guard-verified-ledger-generations.md), without replacing their policies.

`scripts/check_speed_contract.py` is content-free pairing/threshold replay, not
production ingestion coverage. `scripts/check_speed_ingestion.py` verifies only
the original bounded, hash-matching frozen tails via whole-object, full, append
and production-budget recovery paths, reconciles trusted deltas, and compares
model/daily/hourly usability across thresholds. It reads the ledger query-only,
keeps raw copies temporary and private output ignored, and reports unavailable
or changed samples explicitly. This is selected-sample coverage, not a universal
format or timing-quality guarantee.
