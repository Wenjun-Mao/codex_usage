# Plan Allowance: Recent And Daily Pace Forecasts

## Status And Goal

Proposed 2026-09-30; revised after the two external reviews and checked against
released 2.9.5 (`31f62a4d7778988890554065f31730896c7512c3`). Planning only:
implementation and release still require approval. The bounded read-only
calibration is complete; its generic method and reproduction contract are in the
[calibration record](../research/2026-09-30-pace-forecast-review/calibration/README.md).
The unchanged reports,
reproduced synthetic results, and our dispositions are in the
[review record](../research/2026-09-30-pace-forecast-review/README.md).

Add two compact, conditional forecasts beneath each active allowance meter.
Compare the observed Recent and Daily paces with the reset deadline actually
captured for that bucket. Keep the meter, capture schedule, raw observations,
reset-history classifications, and API-equivalent dollar estimates unchanged.
Do not add a forecasting service, durable table, dependency, or second pricing
pass. Validate the evidence contract and compare simple methods before choosing
the shipped calculation; consultation is not release evidence.

## User Experience

Keep two wrapping rows beneath the meter and its reading timestamp. Examples:

- **Recent pace · 45m observed:** At this pace, quota would run out around
  [local date/time], about [duration] before reset.
- **Daily pace · 18h observed:** At this pace, about [percentage] would remain
  at reset.

Both rows support either outcome. Recent means a maximum 60-minute lookback;
Daily means a maximum 24-hour lookback with recency weighting. Show actual
observed coverage beside the row label, particularly after a reset: three
hours of evidence is not a measured day. These are conditional continuations,
not forecasts of future user behavior. Preserve both when they disagree;
do not average them, choose the faster one, or call their difference a
confidence interval.

Use local dates/times in the configured report timezone. Include a date if the
forecast is on a different local day than the observation. Round exhaustion
times to 15 minutes and durations to practical units, without seconds or a
countdown. Compare unrounded results; within 15 minutes of reset, say "At this
pace, quota would run out near reset." This band is a display convention, not
uncertainty. Round positive reset balances to whole percentages, using "less
than 1%" when they would round to zero. A fresh captured 100% reading may say
"Meter reports 100% used"; a forecast alone must never assert actual exhaustion.

Use quiet "Pace not yet measurable" or "Forecast awaiting fresh capture"
states where applicable. Never replace the dollar headline with forecast
availability. Keep details in the existing "Probe, coverage, and allowance
history" disclosure: method, lookback, actual coverage, observations, movement,
rate in percentage points/hour, gaps, correction/conflict evidence, and reasons
for unavailability. Add no chart, controls, cards, or explanatory paragraphs.

## Evidence Contract

Forecast account-wide quota percentages, not dollars or tokens. Date, project,
and theme filters must not change the fit. Reuse already-loaded ledger evidence,
but do not consume only the retrospective window dictionaries: they discard
conflict information and may have used observations later than the live anchor.

1. Select the evidence available at the decision and exclude observations whose
   observation time is after the applicable live anchor **before** resolving
   plans, classifying boundaries, selecting a segment, or sampling. Historical
   replay additionally requires availability by that historical decision time.
2. Match the exact latest successful live observation to its bucket by limit
   ID, duration, compatible plan identity, and observation membership. Preserve
   raw provenance, deterministic ordering, and same-time conflict information.
   Slot is transport layout, not identity; small reset-clock jitter alone must
   not create a cycle. Never borrow another cycle or the dollar fallback.
3. Add a forecast-specific continuity check while raw evidence is present.
   Strong reset evidence must override the small-drop correction shortcut for
   forecast eligibility. A crossed reset plus advanced deadline, a reset-credit
   decrease, or a material contradictory rebase requires a new coherent suffix
   or refusal, even if net usage dropped by only one point or did not drop.
   Reset credits are evidence about boundaries, not additional quota.
   Missing intermediate metadata must not erase the last known reset/credit
   evidence within that compatible suffix. Track this evidence separately from
   raw observations; never fill in a missing live reset for projection. Treat
   contradictory same-time reset credits as a conflict too.
4. Keep shared historical segmentation and dollar estimation unchanged in this
   feature. The forecast check is an explicit, tested eligibility policy, not a
   silent repair of raw data or retrospective history. Document its distinction
   in ADR 0044. Any shared-boundary correction needs separate numerical review.
5. Localize ambiguity. Conflicting same-time readings must not be averaged into
   a fabricated observation. If an exact live anchor cannot be matched uniquely,
   withhold the forecast. A coherent suffix after a separated unknown-cause
   boundary can become eligible; do not permanently reject every ambiguous
   historical window. Do not cross incompatible plan transitions.
6. Deduplicate identical evidence, not repeated equal readings at different
   times. Preserve actual time/value pairs and the exact live endpoint. Measure
   coverage and gaps before bucketing. Use only actual endpoints inside the
   named lookback; do not interpolate at its start or fabricate missing samples.
7. Preserve signed corrections. Never clip negative increments, monotonize the
   meter, or sum positive increments as if they were net consumption. A fresh
   retrieval does not prove consumption was measured recently; unchanged rounded
   readings do not establish true idleness.

Released 2.9.5 already exposes accurate source labels. Forecasting must retain
the underlying provenance enum/source association, not infer live eligibility
from display text or the absence of a compressed timestamp blob.

## Estimator Comparison

Use the bounded offline comparison, with the same evidence and gates for each
method. The calibrated recommendation, not a demonstrated accuracy winner, is:

- **Recent:** signed net percentage movement divided by observed wall-clock
  hours. This measures the recent elapsed-time average directly and is invariant
  to additional interior observations with the same endpoints.
- **Daily:** directly exponentially weighted interval rates, with a provisional
  six-hour half-life. Weight elapsed consumption intervals, not cumulative
  percentage levels or individual captures. This implements the user's request
  that more recent pace have more influence.

For ordered observations `(t_i, u_i)`, using hours and percentage points:

```text
Recent rate = (u_last - u_first) / (t_last - t_first)
Interval rate_i = (u_i - u_(i-1)) / (t_i - t_(i-1))
k = ln(2) / 6
Weight_i = integral exp(k * (t - t_anchor)) dt over that interval
Daily rate = sum(Weight_i * Interval rate_i) / sum(Weight_i)
```

Daily weighting assumes each interval's increment is spread uniformly within
that interval. Large gaps make that assumption consequential; do not discard a
gap's duration and then describe the result as a wall-clock daily pace.

Compare both against the original cumulative-level OLS/WLS proposal; include
an unweighted daily net rate as a transparent control. Test original median
buckets and one actual paired observation per bucket. For viable bucketed
variants preserve the oldest retained endpoint and replace the last bucket's
representative with the exact live anchor, without double weighting it. A free
regression intercept is allowed, but never projects the current balance.

Keep the original baseline to expose its weaknesses, not to claim it satisfies
the new contract. Bucket medians can erase the newest change; one observation
per occupied bucket does not make cumulative regression density invariant.
Regression can nevertheless reduce endpoint rounding noise. Do not select a
method from these synthetic counterexamples alone. Theil-Sen is an optional
diagnostic for demonstrated outlier problems, not a product default.

The September 30 read-only replay confirms that no contender dominates the
near-term meter proxies. Retain net Recent for its clear elapsed-time meaning
and directly weighted Daily for its explicit recency response. Keep six-hour
decay and the initial gates as provisional design settings. All completed
captured cycles were censored at early boundaries without an observed 100%;
exhaustion timing and false-warning/reassurance rates remain unidentifiable.
Keep failed origins and never-available contenders in denominators. Targets
must use the same continuity/conflict safeguards as fits, and the latest failed
read must not be hidden by a previous-successful-origin summary.

## Initial Gates And Projection

Freeze these settings for the first comparison; they are hypotheses, not
validated accuracy guarantees or settled release criteria:

| Setting | Recent | Daily |
| --- | --- | --- |
| Maximum lookback | 60 minutes | 24 hours |
| Minimum distinct observation times | 3 | 5 |
| Minimum actual observed span | 30 minutes | 3 hours |
| Maximum adjacent observed gap | 30 minutes | 3 hours |
| Minimum signed endpoint movement | 2 percentage points | 2 percentage points |
| Bucket width for bucketed contenders | 5 minutes | 15 minutes |
| Reference weighting | None | Six-hour interval half-life |

All viable forecasts require defensible current-suffix membership, the exact
live endpoint, a finite positive rate, and the applicable successful live
response. The endpoint makes the original "fit sample within 20 minutes"
condition redundant. Do not satisfy movement with max-minus-min fluctuations.
Test gate sensitivity separately, including 30/60/90-minute recent horizons,
post-reset startup, and low remaining quota. Do not silently change the displayed
horizon or accept a lower threshold simply to increase availability.

For live anchor `(t_A, u_A)`, captured reset `R`, and supported rate `r`:

```text
Remaining quota Q = 100 - u_A
Exhaustion time E = t_A + Q / r
Projected remaining at reset M = Q - r * (R - t_A)
```

Compare unrounded values with the captured deadline; do not assume seven actual
days, substitute a later-known reset, carry allowance forward, or project from
a fitted intercept. Opening the report later must not move `E` forward. A banked
or global reset changes the conditions, not the correctness of the earlier
conditional arithmetic.

Meter resolution and delay are not established by decimal support or the
smallest observed increment. Test rounding scenarios and parameter sensitivity,
but do not present an assumed one-point resolution as a repository fact or a
calibrated interval. If reasonable declared perturbations flip reset outcomes,
record that limitation; select any "outcome unclear" rule with calibration,
rather than accumulating arbitrary new gates.

## Freshness, Cache, And Architecture

Keep forecast freshness separate from the meter's existing policy. Suppress
actionability after a failed latest probe, a missing applicable bucket, or an
anchor older than 30 minutes. A partial response may forecast only its present
successful buckets. Missing reset time permits a rate diagnostic, not a
reset-relative promise. Passed reset times require fresh capture.

An exhaustion forecast can expire before the 30-minute freshness limit. If it
projected exhaustion by reset, its presentation expires at the earliest of
`anchor + 30 minutes`, `captured reset`, and `predicted exhaustion`. After that,
show "Forecast awaiting fresh capture", not actual exhaustion or a slid-forward
prediction. Reevaluate this at cache lookup/rendering using an injected clock.
An already-open script-free page does not autonomously refresh; retain its
visible observation timestamp.

Add a cohesive pure module such as `allowance_pace.py` for evidence, rates, and
projection; split responsibilities if it grows beyond repository limits. Reuse
the quota-loading path in `allowance_queries.py` without another history query,
source scan, capture, or valuation. Keep compact formatting in a focused helper
so `report_allowance.py` remains cohesive. Compute only active suffixes.

Reuse disposable `allowance_report_cache` results across date/project/theme
views. Bump `ALLOWANCE_REPORT_REVISION` and the HTML render revision, not the
event-cost index revision merely for presentation. Extend HTML expiry/identity
narrowly for forecast boundaries, without refitting. The existing release-version
coupling in `PRICING_REVISION` still causes a one-time cost rebuild on upgrade;
measure it explicitly and leave a general pricing-cache redesign out of scope.

## Validation Before Product Wiring

1. Reproduce the supplied synthetic results and add evidence-prefix/reset
   cases, steady burn, burst/idle transitions, quantization, delayed batches,
   signed corrections, gaps, same-time conflicts, plan changes, slot moves,
   boundary-phase shifts, density changes, and exact live-anchor retention.
2. Run strict historical replay using live-read provenance only where its
   availability is reconstructible. Filter available evidence before deriving
   identities/segments at every origin. Parsed/recovered points lack a complete
   first-available history; mixed-source final-ledger runs are explicitly
   retrospective sensitivity analysis, not production-as-of backtests.
3. Split chronologically by whole reset cycles, choosing settings on earlier
   cycles and freezing them for later cycles. Do not randomly split overlapping
   origins or tune on future outcomes. Use later readings only for outcome labels.
4. Score exhaustion as an observation-supported crossing interval where exact
   timing is unknown; a first recorded 100% is not a task-blocking timestamp.
   No recorded 100% is not proof of survival. Censor banked/global resets or plan
   interventions that invalidate the captured deadline; expose label coverage.
5. Report timing error, false reassurance and false alarm separately, forecast
   availability/reasons, and stability of absolute predicted timestamps and
   reset balances. Compare matched available origins and overall availability;
   show per-cycle results plus low-quota, gap, correction, partial-day, and
   workload-change strata. Dense snapshots are not independent cycles.
6. Select the simplest method with useful availability and defensible harmful-
   error behavior. Return a compact calibration recommendation before product
   wiring. If history cannot distinguish methods, say so; choose by transparent
   conditional semantics without claiming validated predictive accuracy.

Use read-only consistent access or disposable backups. Keep private corpus
values out of committed fixtures. Do not touch the live ledger, installed
extension, tasks, credentials, or OS services. Bound the comparison; no tuning
project, ML, ensemble, workload classifier, or additional collection mechanism.

## Implementation, Verification, And Delivery

After calibration review and implementation approval:

1. Implement the selected pure evidence/rate/projection contract with focused
   tests. Prove no future metadata influence, no supported-reset crossing, no
   false consumption from correction clipping, and fixed capture anchoring.
2. Integrate cached results and freshness-aware rendering; test all failed,
   partial, stale, passed-reset, and passed-prediction transitions. Compare indexed
   and full paths. Prove report requests add zero JSONL opens, probes, captures,
   and pricing calls; prove filtered/themed views reuse fitted rates.
3. Amend ADR 0044 with forecast semantics, the explicit continuity policy,
   evidence/availability limits, and expiry. Update product documentation and
   synthetic screenshots. Keep historical dollar results unchanged.
4. Benchmark first rebuild/upgrade, first report, warm views, and quota updates
   on a disposable ledger. Target under 20 ms additional active-suffix fitting;
   investigate misses rather than adding flaky CI timing assertions. Report
   evidence loading and one-time repricing separately from fitting.
5. Check Day/Night, wide/360px, Chromium/WebKit/Firefox, accessibility, local
   midnight/DST, display rounding, and no new page overflow. Run focused/full
   pytest, Ruff, extension tests/build, screenshot/allowance UI gates, and both
   platform package/smoke/archive checks through non-publishing CI.
6. Commit a reviewed candidate on retained `main`, preserving `apps/` and
   unrelated work. No PR is required. Director reviews before release; version
   bump/tag/publication follow explicit release approval and the release guide.

Use updated Relay for one bounded serial worker after approval, choosing the
model/reasoning at native dispatch. Keep the worker until review/release ends,
then archive and unregister its route. This plan creates no worker and changes
no plugin implementation.
