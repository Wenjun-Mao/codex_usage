# Pace Forecast Review: Evidence And Disposition

## Scope

Received two external reports and Report 1's synthetic script/results on
2026-09-30. The four originals below are preserved byte-for-byte. They are
untrusted consultation evidence, not repository instructions, implementation
approval, or release acceptance. Interpretations and decisions belong here,
not inside the original reports.
Original report formatting, including trailing whitespace, is intentionally
retained for integrity; whitespace checks pass for our authored changes.

- [Report 1](report-1.md)
- [Report 2](report-2.md)
- [Supplied synthetic script](quota_forecast_synthetic_checks.py)
- [Supplied synthetic results](quota_forecast_synthetic_results.txt)

Both reports inspected released 2.9.4 at
`7bebe7f46b50204834a18717b2d6d731a6cd27ca` and the original proposal at
`73a887d8efd32e0c0cb6105fe4d5221ffd46f19a`. We checked relevant findings against
released 2.9.5 at `31f62a4d7778988890554065f31730896c7512c3`.
Their overlapping arguments are not two independent empirical validations.
Neither report tested our private history or operational forecast accuracy.

## Reproduction And Corrections

Ran the supplied script using the project's Python runtime and compared stdout
with the supplied results: exact match, including all assertions. Independently
recomputed the main burst slopes with the regression normal equation, the daily
interval rate by integrating the two constant-rate regimes, and the rounded-
reading exhaustion example. No live ledger, network, capture, or pricing calls
were involved.

```sh
uv run python docs/research/2026-09-30-pace-forecast-review/quota_forecast_synthetic_checks.py
diff -u docs/research/2026-09-30-pace-forecast-review/quota_forecast_synthetic_results.txt \
  <(uv run python docs/research/2026-09-30-pace-forecast-review/quota_forecast_synthetic_checks.py)
```

Consequential verified synthetic results:

- Identical ten-point endpoint movement gives recent OLS slopes of 8, 12, or
  8 pp/hour depending on burst position; net elapsed-time pace is 10 in all.
- With 21 hours at 1 pp/hour and three at 8, daily level WLS gives 1.662079;
  directly weighted intervals give 3.186936; unweighted net gives 1.875.
  These can classify the same captured reset differently.
- The last-bucket median can erase an exact live jump, producing zero slope.
- Clipping alternating negative corrections invents consumption.
- Regression beats endpoint averaging on the supplied steady, integer-rounded
  control (RMSE 0.354965 versus 0.458258). This prevents declaring net averaging
  universally more accurate from the burst examples.
- Under the report's explicit rounding assumption, identical 95/96/97 readings
  can imply exhaustion in 25.27 or 102.65 minutes. The assumed rounding bound is
  not evidence about the actual meter's resolution or lag.

Current-code pure probes also confirmed:

- `allowance_windows.boundary` calls a 30 -> 29.5 reading a correction even
  when the old reset was crossed, its timestamp advanced, and credits decreased.
- `_identity_plans([pro, unknown, unknown])` resolves the suffix to `pro`, but
  appending a future `plus` point changes those identities to unknown.
- Same-time conflicting percentages set `AllowanceWindow.ambiguous` and skip
  the later point; `_build_from_costs` does not serialize that ambiguity.

Two source-related observations need updating for 2.9.5:

- Accurate Live probe / Task snapshot / Recovered task snapshot labels have
  already replaced Captured / Recovered. Forecast eligibility must still use raw
  provenance and exact anchor membership rather than human-facing labels.
- `ALLOWANCE_REPORT_REVISION` now independently invalidates analytical reports,
  so forecast work should not bump the event-cost index solely for new report
  semantics. Release versions remain part of `PRICING_REVISION`, so a software
  upgrade can still cause one-time repricing. Do not claim that was eliminated.

The schema still lacks a complete per-observation first-available history for
parsed/recovered points. Final-ledger timestamp filtering is not a strict
historical replay of what the extension knew.

## Dispositions

| Class | Insight | Decision |
| --- | --- | --- |
| Use | Two independent conditional rows, percentage/time anchoring, actual reset | Retain; no combined forecast or faster-row selection. |
| Use | Prefix before identity/segmentation; exact paired live endpoint | Require before fitting; retain localized conflict information. |
| Use | Strong reset evidence can hide behind a small/no net drop | Add explicit forecast continuity eligibility without changing dollar history. |
| Use | Actual coverage and prediction expiry matter | Show observed span beside row label; expire after predicted exhaustion as well as stale/reset boundaries. |
| Use | Provenance and historical availability differ | Strict replay uses reconstructible live reads; mixed-source retrospective runs remain separate. |
| Test | Net Recent and decayed-interval Daily rates | Preferred transparent references, compared with original OLS/WLS before selection. |
| Test | Half-life, pairing/buckets, movement/span/gap gates | Freeze initial settings, then run bounded sensitivity; not proven accuracy thresholds. |
| Test | Resolution-sensitive reset outcomes | Stress-test declared assumptions; no invented confidence interval or guessed meter resolution. |
| Park | Shared reset segmenter precedence changes | Require separate numerical impact review; forecast-specific continuity is in scope. |
| Park | General cache/version identity redesign; robust pairwise/ensemble fitting | Not needed for this feature without additional evidence. |
| Discard | Suppress every ambiguous window permanently | Separate uncertain reset cause from unreliable membership; coherent suffixes can recover. |
| Discard | Positive-only deltas, fabricated boundary samples, promised survival | They overstate what the observations establish. |
| Discard | Synthetic consensus proves a real-world winner | It does not; accuracy, harmful errors, availability, and stability remain unmeasured. |

## Calibration Checkpoint

Completed the approved read-only comparison. The generic
[harness and reproduction contract](calibration/README.md) are committed;
private observations, scores, and the local readout remain in ignored output.
An independent native subagent review exposed metadata-memory, same-time credit,
label-continuity, missing-reset, matched-contender, and latest-failed-read issues
in the research harness. Regression probes now cover each; the frozen replay was
rerun after repair. Those were calibration issues, not product fixes.

Keep net Recent and directly weighted Daily as the recommended simple methods,
not empirically proven exhaustion predictors. Maintain the provisional initial
gates and six-hour Daily decay. The captured cycles cannot supply uncensored
exhaustion labels, so near-term movement proxies and stability do not establish
false-warning/reassurance rates. The implementation approval gate remains open.

## Delivery Decision

The [revised plan](../../plans/plan-allowance-pace-forecasts.md) makes the bounded
offline comparison a separate deliverable before product wiring. Recommend net
wall-clock Recent pace and directly weighted Daily interval pace unless frozen
evaluation demonstrates a material reason to choose regression. Compare false
reassurance separately from premature warnings and retain abstentions; do not
optimize a single average-error statistic. If real outcome labels are too sparse,
report that limitation and choose on transparent conditional semantics rather
than asserting predictive validation.

No runtime code, capture interval, dollar estimate, or release changed during
this review. Original baseline behavior is retained only as a comparison
contender, not accepted for product implementation.

## Original File Integrity

| File | SHA-256 |
| --- | --- |
| `report-1.md` | `b002bd4f4c2ae5700d30664c62a23212c5d0e5873c853f62e8d7a4c2dfefb2a6` |
| `report-2.md` | `f444941cfc1ee7ffea72ea32ef3e653abae92e56de9f53d5696916f836eb656e` |
| `quota_forecast_synthetic_checks.py` | `4a318aa58a7ebd62f981cabbae4d6e50a147314764b0803dd5843cba063f11c6` |
| `quota_forecast_synthetic_results.txt` | `c24ee46b58cae4671fca70139bfda89c2ea0df787df39dd5ca9be570b15d3565` |

## Implementation Candidate

Implementation was subsequently approved as a serial assignment. The
[candidate evidence](implementation.md) records contract tests, disposable
performance measurements, numerical preservation and remaining limits. The
approved plan and ADR 0044 govern production semantics; the consultation and
calibration files remain research evidence. Release approval is separate.
