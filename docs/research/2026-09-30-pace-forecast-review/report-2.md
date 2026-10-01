## Recommendation

**Keep the two conditional forecasts, but revise the evidence contract before selecting the estimator or approving release.** The architecture is appropriately narrow. The main risks are not computational complexity: they are reset-segment mistakes, misleading treatment of sparse or rounded readings, and interpreting a smoothed historical slope as a forecast of future work.

My preferred **reference methods for comparison** are:

- **Recent pace:** net percentage-point movement divided by observed elapsed time.
- **Daily pace:** an exponentially weighted, elapsed-time-weighted average of interval rates.

Retain the proposed cumulative-level OLS/WLS as the challenger. **The synthetic results do not establish an empirical winner.** They do establish that cumulative-level regression has a less intuitive definition of “pace,” that bucket medians do not eliminate sampling-density effects, and that the provisional gates can admit materially ambiguous forecasts.

The smallest useful next decision is therefore: **fix the reset/as-of eligibility contract, then compare these simple estimators under identical evidence gates.** Do not add an ensemble, confidence interval, workload classifier, or new collection mechanism.

## 1. Inspected evidence and repository findings

I inspected the following pinned revisions, without substituting current `main`:

| Revision | Files inspected |
|---|---|
| Released source **`7bebe7f46b50204834a18717b2d6d731a6cd27ca`**, identified by the brief as v2.9.4 | `src/codex_usage/allowance_windows.py`, `allowance_models.py`, `allowance_queries.py`, `allowance_index.py`, `report_allowance.py`; `docs/adr/0044-plan-allowance-analytics.md`; additionally `allowance_schema.py` and `allowance_store.py` |
| Proposal **`73a887d8efd32e0c0cb6105fe4d5221ffd46f19a`** | `docs/plans/plan-allowance-pace-forecasts.md` and `docs/research/2026-09-30-pace-forecast-review-brief.md` |

The proposal is explicitly planning-only. I accessed published GitHub material and ran synthetic Python calculations; I did not access private observations, run a real-ledger backtest, execute the repository test suite, or implement changes.  

### Repository finding A: “Reuse segmentation” is not sufficient to guarantee “never cross resets”

In **`allowance_windows.py::boundary`**, this check occurs before reset-clock and reset-credit checks:

```python
if 0 < drop <= 1:
    return "correction"
```

Consequently, a reading falling from **1% to 0% across an advertised reset**, with the reset timestamp advancing, is classified as a correction. A simultaneous credit decrease would not override that early return either. This follows directly from the released control flow; it is not a claim about how often it occurs in practice. 

**Change:** stronger reset evidence must be considered before the small-drop shortcut, or forecasting must reject a segment containing that contradiction. Merely matching the live reading to the existing ongoing segment does not repair it.

### Repository finding B: segmentation itself can use later information

**`allowance_windows.py::_identity_plans`** resolves missing plans using neighboring known observations, including following observations. **`segment_windows`** also considers nearby boundary candidates across buckets when classifying global-reset-compatible events. Therefore, filtering observations *after* segmenting the complete history is not an as-of calculation. 

**Change:** apply the historical availability cutoff before identity resolution, reset classification, bucketing, or fitting. This matters both in backtests and when parsed observations extend beyond an older live anchor.

### Repository finding C: forecast eligibility should be computed before evidence is discarded

**`allowance_queries.py::_build_from_costs`** expands compressed recovered timestamps, builds observation provenance, and calls `segment_windows`. Its exported window dictionaries retain correction counts and selected points, but omit the window’s `ambiguous` flag. The segmenter can discard a conflicting same-timestamp point while retaining ambiguity internally.  

Compute forecast eligibility while that information remains available. However, do not blindly translate every `ambiguous` flag into permanent unavailability: **uncertainty about why a boundary occurred is different from uncertainty about which observations belong together**. A clearly observed boundary can be respected without knowing its cause.

### Repository finding D: the existing cache and freshness paths support the proposed architecture, with qualifications

**`allowance_queries.py::allowance_status`** preserves the last successful live readings after a failed probe. Its current age-based stale threshold is one hour, whereas the proposal requires forecasts to expire after 30 minutes. These must remain separate policies. 

**`allowance_index.py::indexed_allowance_report`** caches the analytical report by ledger revision, pricing/index revision, and coverage state, refreshing status on cache hits. That supports caching fitted rates while reevaluating presentation eligibility without refitting. The plan already recognizes the analytical-revision/cost-cache coupling and separate HTML expiry requirement.  

The released renderer already shows successful observation timestamps and configured-timezone reset information. Preserve these rather than making an old forecast appear newly observed.  

## 2. Strongest synthetic counterexamples

Everything in this section is **synthetic mathematical evidence**, not validation on account history.

### A. Moving the same burst changes the reset outcome

Take five observations, 15 minutes apart, over one hour. All traces finish at **80% used**, and reset occurs **two hours after the final capture**.

| Used percentages | Proposed recent OLS | Net elapsed-time pace | OLS forecast |
|---|---:|---:|---|
| `70, 80, 80, 80, 80` | 8 pp/hour | 10 pp/hour | 4% remaining at reset |
| `70, 70, 80, 80, 80` | 12 pp/hour | 10 pp/hour | Exhaustion 20 minutes before reset |
| `70, 70, 70, 70, 80` | 8 pp/hour | 10 pp/hour | 4% remaining at reset |

All pass the proposed recent gates. The first and third are not classified “near reset”: their estimated exhaustion is 30 minutes after reset.

This is not proof that burst timing should be irrelevant. It shows that **OLS is neither “average consumption during this hour” nor “the latest consumption rate.”**

For uniformly spaced dense observations over \([0,H]\), level-regression slope can be written as:

\[
\hat r_{\text{levels}}
=
\int_0^H
\frac{6s(H-s)}{H^3}\,r(s)\,ds.
\]

Its implicit weighting of the underlying rate is **parabolic**, emphasizing the middle and approaching zero at the endpoints. In the five-point example, the four interval-rate weights are \(0.2,0.3,0.3,0.2\), rather than \(0.25\) each.

That is a defensible smoothing rule, but it should be selected deliberately—not mistaken for an elapsed-time average.

### B. A six-hour half-life on cumulative levels is not a six-hour half-life on consumption

I computed both daily estimators on 97 synthetic observations, 15 minutes apart across 24 hours.

| Underlying consumption | Proposed level WLS, six-hour half-life | Exponentially weighted interval mean, six-hour half-life |
|---|---:|---:|
| 2 pp/hour for 18 hours, then idle for six hours | **1.435 pp/hour** | **0.933 pp/hour** |
| Idle for 18 hours, then 2 pp/hour for six hours | **0.565 pp/hour** | **1.067 pp/hour** |

Neither daily estimator is supposed to equal the instantaneous rate. Both intentionally retain history.

The important distinction is semantic: **exponentially weighting cumulative-level observations does not exponentially weight the consumption intervals themselves**. Here, the level fit reacts substantially more slowly to the changed workload.

Keep six hours as an initial test parameter, not as an established responsiveness guarantee.

### C. Two percentage points of movement can still leave the reset outcome unresolved

Assume, solely for this experiment, nearest-whole-percentage rounding.

Three readings 15 minutes apart display:

```text
95%, 96%, 97%
```

The proposed recent estimator reports **4 pp/hour**, giving exhaustion **45 minutes after capture**. All recent gates pass.

Yet both of these perfectly linear underlying traces produce those same rounded observations:

| Underlying percentages | Actual constant rate | Exhaustion if that rate continues |
|---|---:|---:|
| `95.49, 96.00, 96.51` | 2.04 pp/hour | **102.6 minutes** after capture |
| `94.51, 96.00, 97.49` | 5.96 pp/hour | **25.3 minutes** after capture |

With reset 65 minutes after capture, the point forecast says exhaustion **20 minutes before reset**, outside the proposed 15-minute neutral zone. But the two compatible underlying traces give opposite reset outcomes.

This ambiguity exists **without any workload change, missing data, or delayed update**. It is measurement resolution alone. The parser accepts decimal percentages but does not establish a particular rounding-error bound, so the one-point rounding assumption must not be promoted into a repository fact. 

### D. Occupied-bucket medians do not eliminate sampling-density effects

For a synthetic path that rises from 70% to 80% during the first 30 minutes and is then flat:

- Observations every 15 minutes give recent OLS **10.0 pp/hour**.
- Adding observations every five minutes only during the rising portion gives **10.5 pp/hour**.
- Both have the same endpoints and underlying path; the endpoint mean remains **10.0 pp/hour**.

Every added observation occupies a different five-minute bucket. Median bucketing therefore does not remove its extra influence.

Extra observations can reveal genuine structure, so not every resulting change is undesirable. But the proposed guarantee that capture bursts cannot gain extra weight is stronger than what “one sample per occupied bucket” achieves.

### E. Delayed reporting is not identifiable from these observations alone

A fresh capture showing a jump may represent a recent consumption burst, an earlier burst reported late, or a correction. Likewise, fresh unchanged readings can reflect actual idleness or an unchanged rounded/delayed meter.

No estimator using only these fields can reliably distinguish those cases. Do not shift timestamps to “correct lag” without evidence about meter update timing. **Capture freshness establishes when the reading was obtained, not when its consumption occurred.**

## 3. Method comparison and explicit formulas

Let observations be \((t_i,u_i)\), where time is in elapsed hours and usage is in percentage points. Let the live anchor be \((t_A,u_A)\).

### Proposed baseline: cumulative-level OLS/WLS

With \(x_i=t_i-t_A\):

\[
\hat r_L
=
\frac{\sum_i w_i(x_i-\bar x_w)(u_i-\bar u_w)}
     {\sum_i w_i(x_i-\bar x_w)^2}.
\]

Use \(w_i=1\) for recent pace and \(w_i=2^{x_i/6}\) for daily pace.

**Strengths:** inexpensive; uses intermediate readings; can reduce sensitivity to individual endpoint rounding errors when a roughly linear trend is appropriate.

**Weaknesses:** indirect rate weighting; lag after workload changes; dependence on occupied-bucket density; median preprocessing can suppress the freshest change.

Cumulative observations do **not** make descriptive regression inherently invalid. The objection is principally its estimand and behavior—not a blanket claim that cumulative data may never be regressed.

### Alternative 1: net elapsed-time average

\[
\boxed{
\hat r_N=\frac{u_A-u_0}{t_A-t_0}
}
\]

Equivalently:

\[
\hat r_N
=
\frac{\sum_i \Delta t_i(\Delta u_i/\Delta t_i)}
     {\sum_i\Delta t_i}.
\]

This is my preferred **recent-pace reference** because its meaning is direct: measured net percentage-point change per observed wall-clock hour.

It includes flat intervals and is invariant to subdividing the same path without changing endpoints. It is also vulnerable to endpoint errors and can jump when an old burst exits the lookback. It is not automatically more accurate than OLS.

### Alternative 2: exponentially weighted interval average

For consecutive observations:

\[
r_i=\frac{u_i-u_{i-1}}{t_i-t_{i-1}}, \qquad
\lambda=\frac{\ln 2}{6}.
\]

Give each interval its integrated exponential time weight:

\[
W_i=
\int_{t_{i-1}}^{t_i} e^{\lambda(t-t_A)}dt
=
\frac{
e^{\lambda(t_i-t_A)}-e^{\lambda(t_{i-1}-t_A)}
}{\lambda}.
\]

Then:

\[
\boxed{
\hat r_E=\frac{\sum_i W_i r_i}{\sum_i W_i}
}
\]

This is my preferred **daily-pace reference**. Its six-hour half-life applies directly to elapsed consumption intervals.

Its assumption must be explicit: an observed interval’s increment is spread uniformly across that interval for weighting purposes. That does not fabricate extra observations, but it does assume something about timing within a gap. Across an allowed three-hour gap, exponential weights change by a factor of \(2^{3/6}\approx1.41\); that timing ambiguity is not negligible.

Do **not** use an unweighted mean of interval rates. Short, densely sampled intervals would then receive disproportionate influence.

### Alternative 3: median pairwise slope

\[
\hat r_{\mathrm{TS}}
=
\operatorname{median}_{i<j}
\frac{u_j-u_i}{t_j-t_i}.
\]

This is a useful robustness diagnostic, but not my default recommendation. For `70,70,70,70,80`, six of ten pairwise slopes are zero, so the median is zero despite ten points of measured consumption.

A legitimate consumption burst is not necessarily an outlier to remove. “Robust” can mean robustly ignoring the event that matters.

### Practical comparison

| Method | Clearest interpretation | Main weakness |
|---|---|---|
| Level OLS/WLS | Slope of a smoothed cumulative trajectory | Indirect rate weighting and lag |
| Net elapsed-time average | Average measured consumption over the observed span | Endpoint noise and lookback-edge jumps |
| Decayed interval average | Recency-weighted wall-clock consumption | Assumed timing within intervals; update corrections |
| Median pairwise slope | Typical pairwise level slope | Can erase real staircase consumption |

All are feasible in pure Python. There is no reason here for an ML service or additional dependency.

## 4. Preprocessing, anchoring, and gates

### Preprocessing: change the contract before tuning the estimator

**Preserve actual paired observations.** Separately taking median time and median percentage can create an unobserved pair when values are nonmonotonic. For example, `(0,50), (1,54), (2,51)` produces `(1,51)`. For an odd monotone sequence, the medians do align; the problem is conditional, not universal.

For the controlled comparison, test the proposed medians against **one actual paired observation per bucket**, with a deterministic selection rule. My starting challenger would use the latest observation in each bucket, preserving the oldest retained endpoint and the exact live endpoint.

**Do not let the final bucket hide the live anchor.** Several earlier readings around 74% and a final live reading of 90% can yield a median near 74%. The forecast then uses 10% remaining while fitting a slope that scarcely reflects the latest change. That may be intentional smoothing, but it requires an explicit policy and diagnostic.

**Keep repeated equal readings at different times.** They contain elapsed-time information. Deduplicate actual duplicates, not every repeated percentage.

**Do not clip negative increments to zero.** In:

```text
70, 71, 70, 71, 70
```

net movement is zero, but summing only positive increments invents two points of consumption. Preserve signed readings and correction flags. Test restarting the fit after a material correction rather than silently converting corrected data into monotone consumption.

### Endpoint anchoring: keep it, but distinguish two operations

Keep:

\[
\hat T_E=t_A+\frac{100-u_A}{\hat r}.
\]

Do not project from the regression intercept. The current live meter is the appropriate reported remaining-quota anchor.

However, **including the live observation as the final fit point is not the same as forcing the regression line through it**. I would include it, retain a free intercept for OLS/WLS, and inspect endpoint disagreement. Forcing the whole line through a noisy endpoint gives that reading influence over every residual.

Also keep anchoring to **capture time**, not render time. Reopening a report must not move exhaustion forward.

### Explicit initial gates for the comparison

I would retain most proposed numerical gates initially so estimator comparisons are not confounded by different availability policies:

| Parameter | Recent | Daily | Status |
|---|---:|---:|---|
| Maximum lookback | 60 minutes | 24 hours | **Keep** |
| Bucket width for bucketed variants | 5 minutes | 15 minutes | **Test** |
| Minimum occupied buckets | 3 | 5 | **Test** |
| Minimum observed span | 30 minutes | 3 hours | **Test** |
| Maximum adjacent gap | 30 minutes | 3 hours | **Test** |
| Minimum movement | 2 percentage points | 2 percentage points | **Test**, explicitly net endpoint movement |
| Weighting half-life | None | 6 hours | **Test** |
| Maximum live-reading age | 30 minutes | 30 minutes | **Keep provisionally** |

These are **prespecified comparison settings, not validated accuracy thresholds**. Bucket count is not an independent-sample count or a confidence measure.

Require, independently of those settings:

- A uniquely matched live anchor and defensible segment membership, with no contradictory reset evidence.
- No observations beyond the anchor and no future-derived metadata.
- Successful applicable live response; failed or missing bucket responses suppress actionability.
- Finite positive rate, valid time arithmetic, and an advertised reset later than rendering time.
- Actual coverage reported; no manufactured sample at the lookback boundary.

With the exact live endpoint included, the proposed “last fit sample within 20 minutes” rule becomes unnecessary for that variant. Retain it only when evaluating the original median variant.

### Two points of movement is not an error guarantee

For the endpoint estimator, suppose a genuinely established measurement bound is ±\(q/2\) per endpoint. Let observed span be \(L\), and time from anchor to reset be \(d\). Projected remaining quota is:

\[
M=100-u_A-d\frac{u_A-u_0}{L}.
\]

Its worst-case endpoint-measurement sensitivity is:

\[
\boxed{B_M=\frac q2+\frac{qd}{L}}.
\]

This is a deterministic sensitivity bound under that measurement assumption—not a confidence interval and not protection against delayed updates or future behavior.

It illustrates why the same two-point movement can be adequate for one reset horizon and inadequate for another. Do not guess \(q\) from the smallest observed increment. Without a justified measurement model, keep this as a synthetic stress test rather than presenting a numerical uncertainty range.

### Presentation and expiry

Use:

\[
M_R=100-u_A-\hat r(t_R-t_A).
\]

Compare unrounded values. Keep the 15-minute near-reset band as a **display convention**, not a statistical uncertainty interval.

One additional expiry case is necessary: **the projected exhaustion time may already have passed while the live reading remains less than 30 minutes old**. Do not assert actual exhaustion or move the prediction forward; show “Forecast awaiting fresh capture.”

Partial coverage should not look like a measured full day. “24-hour weighted pace — 3 hours observed” is more honest than an unqualified “Daily pace · 24 hours.”

Use conditional wording on both outcomes: **“At this pace…”** rather than a stronger promise that quota “will last.” Keep two separate point estimates; disagreement is not a confidence interval, and selecting the faster forecast would systematically favor premature reset use.

## 5. Minimal leakage-free validation plan

### First: separate estimator correctness from operational usefulness

There are two different questions:

**Conditional-estimator tests:** Given a specified underlying continuation and observation process, does the method estimate the intended historical pace and compute the projection correctly?

**Historical usefulness tests:** Under whatever users actually did afterward, how often would the displayed projection have helped or misled them?

A method can pass the first and perform poorly on the second because future behavior changes. That does not excuse harmful forecasts, but it prevents misdiagnosing every forecast miss as a slope-estimation bug.

### A. Small deterministic synthetic suite

Start with the examples above, plus a compact set covering constant burn, stop/start changes, bursts at both lookback edges, rounded flats, delayed jumps, negative corrections, missing intervals, bucket-phase shifts, and every reset/identity case.

Test hard invariants before aggregate accuracy:

- No fitting across a supported reset or incompatible plan transition.
- No future metadata influence.
- No movement of the absolute forecast when only render time changes.
- No false consumption from clipping corrections.
- Correct stale, failed, expired-reset, and forecast-time-passed transitions.
- Equivalent indexed and full-report outputs.

Also replay the same underlying path with denser active-period sampling and shifted UTC bucket phases. Report changes rather than demanding impossible invariance when new samples reveal genuinely new structure.

### B. Historical replay must respect when information became available

A timestamp cutoff alone is insufficient if an old parsed observation was imported later.

The inspected observation schema and `QuotaObservation` do not provide a per-observation first-seen timestamp. **`allowance_store.py::store_observations`** merges recovered timestamps into compressed state records; provenance identifies sources, not a complete historical availability timeline. Thus the final reconstructed observation table alone does not establish exactly what the extension knew at an earlier moment.   

Use an existing historically faithful replay source where available. Otherwise:

- A **live-only replay** using recorded live-read provenance is a defensible restricted evaluation.
- A replay using all reconstructed historical points must be labeled **retrospective evidence replay**, not production-as-of validation.

No new capture mechanism is required to make that distinction.

The order should be:

```text
for each evaluation cutoff:
    select observations actually available by that cutoff
    select the live anchor available by that cutoff
    exclude observations beyond the anchor
    resolve identities and segment only that eligible prefix
    bucket, gate, and fit using frozen parameters
    save the forecast and its eligibility reasons

use later observations only to construct outcome labels
```

Split chronologically by whole cycles, not random observations. Purge training examples whose outcome periods cross the held-out boundary. Overlapping forecasts from the same cycle are not independent replications.

### C. Score four things, with explicit missing-label handling

| Dimension | Minimum useful measurements |
|---|---|
| **Exhaustion error** | Signed timing error, absolute error, median and upper-tail error; distinguish dangerously late forecasts from prematurely early ones; stratify by remaining percentage and forecast horizon |
| **Reset outcome** | Exhaust-before-reset versus remain-at-reset classification; retain near-reset and unavailable outputs; report false reassurance and false early-exhaustion warnings separately |
| **Availability** | Fraction of eligible opportunities and wall-clock time with a forecast; breakdown by reason, coverage, plan/limit, and remaining quota |
| **Update stability** | Change in absolute predicted exhaustion timestamp, change in projected reset remainder, outcome flips, availability toggles, and response lag after workload changes |

Compare error on **matched available anchors** and report each method’s overall availability. Otherwise, aggressive abstention can masquerade as accuracy.

For stability, track the **absolute predicted timestamp**, not merely time-to-exhaustion: a correctly anchored countdown naturally decreases as time passes. Separate changes after new consumption from changes caused only by recovered history or bucket membership.

### D. Do not manufacture outcome truth

A first recorded 100% reading is not necessarily the instant a task was blocked. With delayed or quantized meters, distinguish **observed meter exhaustion** from actual service exhaustion.

Where appropriate, use interval-censored threshold labels rather than pretending the first 100% timestamp is exact. Where labels are not supportable, mark them unknown. Do not treat a reset as an exhaustion event, or post-reset zero usage as evidence that 100% remained immediately before reset.

A banked/global reset or plan change before the reset advertised at forecast time is an **intervention**. It does not prove the old forecast would have lasted. Censor that original target or score the intervention separately; never substitute the later-known reset schedule into the original forecast.

Finally, report the number of actual exhaustion events and independent cycles. Many thousands of snapshots with no exhaustion events cannot validate protection against interrupted tasks.

## 6. Keep / Change / Test disposition

| Classification | Recommendation |
|---|---|
| **Keep** | Two separate conditional forecasts; actual captured reset; live percentage/time anchor; account-wide scope; observed idle time; quiet unavailable states; pure Python and cached already-loaded evidence |
| **Change** | Address small-drop reset precedence; apply as-of filtering before segmentation; derive forecast-specific ambiguity eligibility before evidence is discarded |
| **Change** | Preserve the exact live endpoint and actual time/value pairing in the challenger; define movement as signed net movement; never clip negative increments |
| **Change** | Expire actionability when the projected exhaustion time has passed; visibly distinguish partial observed coverage from a full-day history |
| **Test** | Level OLS/WLS versus net elapsed-time and decayed interval means under identical gates |
| **Test** | Median versus actual-pair buckets, bucket phase, six-hour half-life, movement/span/gap thresholds, and post-correction restart behavior |
| **Test, not default** | Median pairwise slope as a robustness diagnostic |
| **Do not add** | Uncalibrated confidence intervals, automatic “choose the faster” aggregation, inferred future task behavior, new capture, or a general cache redesign |

**Bottom line:** the proposed feature is worth pursuing, but the current evidence does not justify treating cumulative-level regression or the two-point movement gate as settled. The highest-value changes are contractual and testable: preserve causal evidence boundaries, define precisely what “pace” averages, and evaluate harmful errors together with availability and stability. A simple estimator that survives those tests is preferable to a more elaborate forecast whose apparent precision comes from assumptions the observations cannot support.