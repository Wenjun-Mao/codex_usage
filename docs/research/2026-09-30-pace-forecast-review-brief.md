# External Review: Quota Pace Forecasts

## Handoff Status

Prepared 2026-09-30 with user authorization to commit and push the review
documents. Recommended mode: Pro, one independent reviewer. The product source
below is public and its remote anchor was verified. Verify publication of this
brief and the plan, then bind their documentation commit in the final handoff.
No private ledger, captured account percentages,
task content, credentials, or local paths are part of this packet.

Two returned reports and the supplied synthetic files are now preserved in the
[review record](2026-09-30-pace-forecast-review/README.md), with verification and
our dispositions separate from the originals. The
[implementation plan](../plans/plan-allowance-pace-forecasts.md) has been revised
after review; the prompt below preserves the originally submitted proposal.

## Consultant Prompt

Review a proposed quota-exhaustion forecasting method for Codex Usage Companion,
a VS Code extension. This is an independent statistical/engineering critique,
not implementation, release acceptance, or a request to confirm our plan.
The user wants two compact conditional forecasts: recent pace and daily pace,
each showing likely exhaustion before reset or expected remaining quota at reset.
A wrong forecast can cause premature banked-reset redemption or unexpected task
interruption. Prefer a useful, simple method with honest limits over false precision.

Access: GitHub only. You cannot access our local ledger, services, task logs,
worktrees, account, or conversation. Do not request or infer their contents.
Repository: https://github.com/Wenjun-Mao/codex_usage
Released source anchor: v2.9.4, commit
7bebe7f46b50204834a18717b2d6d731a6cd27ca.
State the source commit actually inspected; report inaccessible evidence rather
than silently substituting another revision. The proposal below is not released.

Relevant source at that anchor: src/codex_usage/allowance_models.py,
allowance_windows.py (segment_windows), allowance_queries.py,
allowance_index.py, report_allowance.py, and docs/adr/0044-plan-allowance-analytics.md.
Proposed plan: docs/plans/plan-allowance-pace-forecasts.md at the separately
identified documentation commit in the final handoff. No raw user history is supplied.

Evidence shape: stored observations contain timestamp, limit ID, plan (sometimes
missing), primary/secondary slot, duration, used percentage, reset timestamp,
and optional banked-reset credits. Live captures are usually around 15 minutes
apart; parsed historical snapshots can be much denser and bursty. Percentages
support decimals but can be quantized to whole points. Repeated readings,
idle periods, gaps, stale/delayed updates, and small downward corrections occur.
Nominal weekly duration does not guarantee a seven-day actual cycle. Scheduled,
banked, and global resets can split cycles. The existing segmenter resolves
compatible missing-plan metadata without rewriting raw evidence. Slot and small
reset-timestamp jitter are not durable identity. Explicit plan transitions are
separate; reset classifications describe evidence rather than proven causes.

Candidate method, deliberately open to challenge:
- Fit only the ongoing segment matching each active live bucket. Anchor to its
  latest captured percentage/time, exclude later observations, and never stitch resets.
- Recent pace: 60-minute lookback, equal-weight regression of cumulative used
  percentage against elapsed hours; one median time/percentage per occupied
  UTC-aligned five-minute bucket.
- Daily pace: 24-hour lookback, 15-minute median buckets, exponentially weighted
  regression with six-hour half-life. Each occupied bucket gets one sample so
  frequent captures do not dominate. Include observed idle time, not active-work
  time only; do not fabricate samples across unobserved gaps.
- For supported positive slope r, exhaustion = capture time + (100 - captured
  used percentage) / r. Anchor at the actual last reading, not the fitted intercept.
  Compare with the actual captured reset; if reset is earlier, project remaining
  percentage there. Missing or elapsed reset time suppresses reset-relative forecasts.
- Initial recent gates: at least three buckets spanning 30 minutes, no gap over
  30 minutes, at least two percentage points of movement. Daily gates: at least
  five buckets spanning three hours, no gap over three hours, at least two points
  of movement. Both require finite positive slope, last fit sample within 20
  minutes of anchor, and live reading age at most 30 minutes. Gates are provisional.
- Sparse/flat/nonpositive fits show a quiet unavailable row, not a promise of
  lasting until reset. Forecasts use local time rounded to 15 minutes; exhaustion
  within 15 minutes of reset is "near reset". Details stay collapsed; no new chart,
  controls, countdown, capture, token pricing pass, or network calls. Cached
  presentation expires when freshness/reset boundaries are crossed, without refitting.

Main questions:
1. Is fitting cumulative percentage levels the right way to estimate recent
   consumption, or do interval rates, robust local fits, time-weighted smoothing,
   or another comparably simple method handle bursts and idle periods better?
2. Are median buckets and six-hour half-life justified? Address sampling-density
   bias, gaps, quantization, delayed readings, corrections, serial dependence,
   endpoint anchoring, and lag after a workload change. Challenge arbitrary gates.
3. What does "at this pace" validly mean? Separate conditional continuation from
   a forecast of future user behavior. Explain when reset-relative claims need
   softer wording or suppression, particularly after long idle periods or near zero.
4. Can a small robust range improve the display without pretending to be a
   calibrated confidence interval? Recommend a point estimate if that is more honest.
5. What minimal synthetic experiments and leakage-free historical backtests
   would let us choose the method and parameters before shipping?

Compare our baseline with two or three viable simple alternatives. Use small
synthetic examples for steady burn, burst-then-idle, idle-then-burst, uneven
capture density, rounded/lagged readings, corrections, sparse gaps, and resets.
Give executable Python or pseudocode where it improves falsifiability. Clearly
label synthetic results; do not claim performance on unavailable private data.
For backtests, forbid future samples and retrospective metadata leakage; include
error versus remaining quota and forecast horizon, reset-before-exhaustion
classification, update stability, and forecast availability. Evaluate recorded
history within its observed coverage rather than assuming every actual reset is known.

Constraints: no ML service or new capture data, no transcript inspection, and
no unnecessary dependency or complex model. Pure Python on already-loaded
observations should be cheap (initial target: under 20 ms additional fitting for
active segments). Keep distinct one-hour and 24-hour UI meanings; do not silently
substitute a horizon. Genuine evidence gaps may require returning no forecast.

Return an answer-first recommendation, strongest counterexamples to our plan,
a method comparison, explicit formulas/parameters/gates, minimal validation plan,
and suggested changes classified as Keep, Change, or Test. Separate inspected
repository facts from mathematical reasoning, assumptions, and synthetic evidence.
Cite repository findings with commit/path/symbol and any external claims with
primary-source links. No broad literature survey is required. You may conclude
that the baseline is adequate, but support that conclusion rather than deferring
to our proposed design.

## Return Handling

Preserve the returned report unchanged. Record our review separately, classifying
individual insights as Use, Test, Park, or Discard. Verify only relied-on claims
before revising the implementation plan. Consultation does not approve a release.
