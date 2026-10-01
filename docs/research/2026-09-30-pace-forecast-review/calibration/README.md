# Bounded Pace Calibration

## Scope

This analysis-only harness compares the two proposed conditional pace rows.
It does not implement forecasts in the extension or establish release acceptance.
The reference methods are signed net Recent movement and exponentially weighted
Daily interval rates. Original median-bucket and actual-pair cumulative OLS/WLS
remain comparison controls. All contenders use identical raw-evidence gates.

The September 30 calibration supports keeping those transparent references,
not claiming them as predictive-accuracy winners. Recent regression slightly
improves some near-term movement errors; direct Daily weighting responds to
workload changes more directly. Six-hour decay remains a provisional design
choice, not an optimized universal parameter. Keep the initial two-point
movement threshold for now; sensitivity does not establish the safest threshold.

No completed captured cycle supplies an uncensored exhaustion outcome. Dense
origins are overlapping observations, not independent weekly experiments.
That prevents empirical exhaustion-time, false-reassurance, or false-alarm claims.
The private readout and results belong under ignored `output/research/`, not in
committed corpus fixtures. The implementation plan retains the approval gate.

## Reproduce

Run from the repository root with the existing Python runtime. Supply the
ledger path and an ignored output directory; these are operator choices, not
hardcoded machine paths.

```sh
CALIBRATION=docs/research/2026-09-30-pace-forecast-review/calibration
OUT=output/research/pace-calibration
uv run python "$CALIBRATION/snapshot.py" --ledger "$LEDGER" --output "$OUT/snapshot.json"
uv run python "$CALIBRATION/checks.py"
uv run python "$CALIBRATION/replay.py" --snapshot "$OUT/snapshot.json" --output "$OUT/results.json"
uvx ruff check "$CALIBRATION"
```

The extractor opens SQLite with `mode=ro`, enables `query_only`, and uses one
transaction. It exports only quota metadata, read outcomes, and provenance;
it asserts zero SQLite changes. It opens no rollouts and invokes no capture,
probe, backfill, pricing, service, or extension operation. Output permissions
are restricted to the current user. Decompression is limited to quota timestamp
blobs already in the ledger. The SQL files are the extraction contract.

## Replay Contract

- **Strict live-only:** quota-read insertion order establishes availability.
  Only live records retrieved by the origin are usable. Observation timestamps
  are additionally cut off before causal plan resolution and continuity checks.
- **Reconstructed sensitivity:** final-ledger task/recovery evidence is cut off
  by observation time, but its historical first availability is unknown. This
  is explicitly retrospective and must not be scored as production-as-of accuracy.
- **Boundaries:** crossed reset plus advanced deadline, reset-credit decrease,
  material deadline rebase, large drops, or incompatible plans cut continuity.
  Strong evidence takes precedence over a small/no drop. Small reset-clock
  jitter alone does not split a cycle. Missing intermediate metadata does not
  erase compatible last-known boundary evidence, but never fills in a missing
  live reset for projection. The product's dollar segmenter is unused.
- **Anchors:** same-time conflicts are not averaged. A later coherent suffix can
  recover. Use the actual live timestamp/value pair; do not use a regression
  intercept, future plan metadata, or a fabricated lookback endpoint.
  Same-time reset-credit contradictions also prevent fitting and target labeling.
- **Corrections:** signed increments are retained, not clipped or monotonized.
  Equal values at different times retain their wall-clock duration.
- **Common gates:** Recent uses 60 minutes, three timestamps, 30-minute span and
  maximum gap, and two net percentage points. Daily uses 24 hours, five times,
  three-hour span and maximum gap, and two net points. Six-hour half-life weights
  interval exposure. A 30-minute sensitivity variant explicitly uses a 15-minute
  minimum span; a 30-minute minimum would be structurally inapplicable unless
  the oldest sample falls exactly on the lookback boundary.

## What Is Scored

Every recorded quota read is an opportunity, including failed/missing applicable
live buckets. Report successful-origin availability separately. Use cycles 0/1
as the earlier cohort and 2/3 as the later cohort; all initial settings were
fixed by the plan, not tuned against future labels. Sensitivities are descriptive
checks, not selections optimized on the later cohort.

Near-term proxy targets are the first actual live reading at least one/three
hours later, no more than 15 minutes late, in the same continuity cycle, with
no intervening observed gap over 30 minutes. No target value is interpolated.
The proxy is absolute error of `used + rate * actual_elapsed_hours`; it is not
exhaustion-time error. Both uncapped linear and capped 0-100 meter errors are
recorded. Do not silently cap the linear proxy to hide an overly fast pace.
Compare only matched available origins for contender rankings.
Keep every declared contender in that set even if it never produces a forecast;
its refusal must not silently improve another method's matched score. The latest
read and the latest successful origin are separate outputs, so a failed latest
read cannot masquerade as an actionable older forecast. Target labeling uses
the same causal continuity rules and excludes contradictory same-time values.

Record availability changes, reset-outcome flips, and changes in the absolute
predicted exhaustion time between adjacent available origins within 30 minutes
and the same cycle. These are sensitivity/stability measures, not errors against
ground truth. Outcomes ending at an intervention are censored, not survivals.
Absent recorded 100% usage never proves that quota was available until reset.

Rates assume consumption is uniformly spread within each observed interval.
Actual meter resolution and lag remain unknown. One-point sensitivity introduces
slower regimes, so its lower movement error must not be interpreted as a fair
head-to-head accuracy win over the two-point gate.

## Remaining Product Gates

The harness does not test the extension's failed/partial/stale rendering,
prediction expiry, cache lookup, installed package, timezone display, or UI.
Those remain in the implementation plan. Full-prefix reconstruction is a replay
cost, not an acceptable approach for warm report views: cache causal state and
fit only the active bounded suffix. Separate evidence reconstruction, fitting,
one-time pricing rebuild, and transport when benchmarking integration.
