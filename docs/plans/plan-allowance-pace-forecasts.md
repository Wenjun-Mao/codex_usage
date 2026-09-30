# Plan Allowance: Recent And Daily Pace Forecasts

## Status And Goal

Proposed on 2026-09-30, grounded in released 2.9.4. Planning only; implementation
and publication require approval. Add two compact forecasts beside each active
allowance bucket so users can compare likely exhaustion with its actual reset.
Keep the existing allowance meter and API-equivalent value calculation intact.

## User Experience

Show two wrapping text rows beneath each bucket's meter and reading timestamp:

- **Recent pace · 1 hour:** Estimated to run out around [local date/time],
  about [duration] before reset.
- **Daily pace · 24 hours:** Expected to last until reset, with about
  [percentage] remaining.

Both rows support either outcome. These examples illustrate wording, not
predictions. Use conditional language, not promises: the result assumes the
measured pace continues. Where forecasts disagree, show both without selecting
the faster one, averaging them, or presenting their difference as a confidence
interval. The existing reading timestamp supplies the observation context.

If exhaustion is within 15 minutes of reset, say "Estimated to run out near
reset" rather than suggesting a meaningful lead or surplus. Show "Allowance
exhausted" at a captured 100% usage. Never replace the dollar headline with
forecast availability messaging.

Use local dates/times in the configured report timezone, including a date when
the forecast is not on the observation's local day. Round forecast times to
15 minutes and durations to practical units; do not display seconds or a live
countdown. Round projected remaining percentages to whole percentages, using
"less than 1%" for positive values that would round to zero. Outcome comparisons
use unrounded values. Keep wide/narrow and Day/Night layouts compact, accessible,
and script-free; add no controls, cards, chart, or explanatory paragraphs.

Put horizon, actual observed coverage, bucket count, usage movement, fitted
percentage-points/hour, weighting, gaps, and availability reasons inside the
existing "Probe, coverage, and allowance history" disclosure. Scope diagnostics
to their bucket and distinguish measured readings from extrapolated forecasts.

## Calculation Contract

Forecast account-wide quota percentage, not API-equivalent dollars or tokens.
Reuse already-loaded observations and the released reset segmentation from
ADR 0044. Forecasts ignore project/date/theme filters just like Plan Allowance.

1. Match each live active bucket to its ongoing segment by limit ID, duration,
   derived compatible plan identity, and observation membership. Slot is not
   identity; reset timestamp jitter does not create a new identity. Do not use
   an earlier segment or dollar-headline fallback for pace. If the match is
   ambiguous, no forecast is available for that bucket.
2. Anchor to that bucket's latest captured live observation. Ignore observations
   after the anchor. Use only points within the same segment and lookback;
   never fit across actual resets or explicit/ambiguous plan transitions.
3. Recent pace uses the preceding 60 minutes with equal-weight regression.
   Collapse observations into fixed UTC-aligned 5-minute buckets, taking median
   observation time and median used percentage per occupied bucket. Give every
   occupied bucket one sample. A burst of captures must not gain extra weight.
4. Daily pace uses the preceding 24 hours with 15-minute buckets and a 6-hour
   exponential half-life: weight = 2^(-age_hours / 6). Use the same median
   sampling rule. Include observed idle periods and actual elapsed time; do not
   calculate an active-work-only speed or manufacture samples in missing gaps.
5. Fit used percentage against elapsed hours. For a positive supported slope,
   time to exhaustion = (100 - captured used percentage) / slope. Absolute
   exhaustion time = captured observation time + time to exhaustion. Compare
   this with the latest captured reset timestamp, not a nominal seven-day end.
6. If reset comes first, project the remaining percentage at reset from the
   captured percentage and slope. Do not extrapolate from the fitted intercept,
   fabricate a reset date, or carry unused allowance across windows.

Absolute predictions remain anchored to the capture, so opening a report later
must not slide exhaustion forward. Reset-relative gaps are also fixed at that
capture. No continuously decrementing "time left" label is needed in this slice.

## Evidence And Availability

These pace gates are separate from the dollar estimator's unchanged 10-point
threshold. Initial, explicit acceptance rules are:

- Recent fit: at least three occupied buckets spanning at least 30 minutes,
  no adjacent-sample gap above 30 minutes, and at least two percentage points
  of observed movement.
- Daily fit: at least five occupied buckets spanning at least three hours,
  no adjacent-sample gap above three hours, and at least two percentage points
  of observed movement. A window younger than 24 hours uses only its available
  current-cycle history; disclose the actual coverage, not a full day.
- Both require a finite positive slope and a last fit sample within 20 minutes
  of the live anchor. Missing spans are diagnostics, never assumed complete.
- Forecast readings must be no more than 30 minutes old at rendering. Preserve
  existing freshness labels. A failed latest probe or unavailable bucket
  suppresses its actionable forecast. A partially refreshed probe may forecast
  only buckets actually present in that successful live response.
- If the captured reset has already passed, suppress that forecast until a new
  capture establishes the current state. Missing reset time permits a pace
  diagnostic but not a reset-relative forecast.

Insufficient movement, nonpositive slope, or sparse coverage shows the quiet
row "Pace not yet measurable". Stale/failed readings show "Forecast awaiting
fresh capture". Do not claim unchanged rounded readings prove no consumption
or that a zero slope guarantees survival until reset. Retain specific reasons
only in collapsed diagnostics. Do not silently substitute a different horizon.

Before product wiring, reproduce both proposed fits on a read-only consistent
ledger snapshot. Test 30-, 60-, and 90-minute sensitivity as calibration, not
additional UI choices. Confirm the gates work with the existing approximately
15-minute capture cadence and finer-grained parsed observations. If this exposes
a material weakness in the chosen contract, return that evidence for review;
do not silently relax the gates or change the user-facing forecast horizons.

## Architecture And Performance

Add a cohesive pure forecast module, such as `allowance_pace.py`, for sampling,
fits, evidence gates, and reset comparisons. Integrate through
`allowance_queries.py` using the same segmented observations. Keep reporting
formatting in a focused helper if needed so `report_allowance.py` stays cohesive.
Reuse existing report CSS and status/observation provenance contracts.

Persist only disposable derived results through the existing
`allowance_report_cache`; no ledger schema migration, new durable table, source
scan, network call, capture schedule change, or second valuation pass is needed.
Fit only active segments. Cached views must reuse fits across dates/projects/
themes rather than repeating full-history processing.

Advance the analytical contract and HTML render cache revisions. The current
analytical revision is coupled to cost-cache invalidation; measure and disclose
any one-time rebuild rather than hiding it in warm timings. Do not broaden this
feature into an unrelated cache redesign.

Re-evaluate age/expired-reset presentation from an injected current time at
rendering, without refitting. Extend HTML cache identity/expiry narrowly so the
30-minute forecast freshness boundary and reset-time crossing cannot reuse an
actionable stale forecast. Rendering later must not imply a new capture.

## Verification And Acceptance

1. Pure tests independently reproduce linear and recency-weighted slopes;
   cover quantized/decimal readings, repeated captures, sampling-density changes,
   observed idle periods, missing buckets, sparse/flat/negative fits, and gates.
2. Test current-segment matching, missing plan metadata, explicit plan changes,
   primary/secondary moves, multiple limits/durations, scheduled/banked/global
   resets, meter corrections, and same-timestamp ambiguity. Forecasts must not
   stitch cycles together or depend on the dollar estimator's qualification.
3. Test before/near/after reset outcomes, exhausted quota, missing/past reset
   time, local midnight, DST, date formatting, rounding, and unchanged anchor
   time across later report renders. Check stale/failed/partial probe behavior
   and HTML cache transitions with an injected clock.
4. Compare indexed and full report paths; prove filters/themes reuse fits and
   report requests open zero JSONLs and trigger zero capture/probe calls. Pricing
   calls must not increase because of forecasting.
5. Benchmark before/after on a disposable real-ledger copy: cold analytical
   rebuild, first report, warm views, and after quota capture. Aim for under
   20 ms additional active-segment fitting and no material warm-view regression;
   investigate misses rather than relying on a flaky timing assertion in CI.
6. Verify two-row readability and disclosures in Day/Night, wide/360px views
   across Chromium, WebKit, and Firefox. Ensure no clipping, false precision,
   inaccessible status, or new horizontal page overflow. Refresh canonical
   synthetic screenshots because the shipped interface changes.
7. Run focused tests, `uv run pytest -q`, `uvx ruff check .`, extension tests/
   build, screenshot and allowance UI gates, and both platform package/smoke/
   archive checks through established non-publishing CI.

Keep real local corpus values out of committed fixtures. Use read-only access
or disposable consistent backups for calibration; do not touch the live ledger,
installed extension, tasks, credentials, or OS services during development.

## Delivery Order And Review

1. Capture calibration evidence for both horizons and verify the gate/cadence
   assumptions; preserve useful conclusions, not private corpus values.
2. Implement the pure forecast contract and focused tests.
3. Integrate cached derived results, freshness-aware rendering, compact UI,
   fixtures, and report/no-capture regression tests.
4. Amend ADR 0044 with forecast semantics, evidence gates, conditional wording,
   and cache/ledger-only guardrails. Update relevant product documentation.
5. Run the verification matrix and commit a local candidate on retained `main`.
   Preserve pre-existing `apps/` and unrelated changes. No PR is required.
6. Director reviews implementation and evidence before any release. Version
   bump, changelogs, push/tag, and Marketplace publication follow the established
   release guide only after explicit release approval. Leave the worker intact
   until review/release is complete, then archive and unregister its Relay route.

After implementation approval, use updated Relay with one bounded serial
worker; choose model/reasoning at dispatch. Planning creates no worker and
changes no plugin implementation.
