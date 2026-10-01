## Recommendation

**Keep the two-row feature, but revise the evidence contract before implementation. Do not ship the proposed regressions unchanged, and do not replace them merely because a simpler estimator sounds more robust.**

The most consequential issues are upstream of regression: a reset can survive the released segmenter’s correction rule; retrospective plan resolution can change which observations belong together; and bucket medians can remove the latest live change from the fitted data even though the projection is anchored to that change.

For method selection, run one bounded comparison between:

1. The proposed cumulative-level regressions.
2. **Net percentage change divided by elapsed wall-clock time**, over the recent and daily windows.
3. A **direct exponentially weighted average of interval rates**, principally as the daily challenger.

My preferred starting design is the second method for both horizons: it gives “continue the measured average pace” a transparent meaning and eliminates interior sampling-density influence. However, the synthetic tests below include a steady, rounded-reading case where regression performs better. **Replacing regression is a Test decision; fixing the evidence and anchoring contract is a Change decision.**

No additional capture, machine-learning service, durable ledger table, or external dependency is justified.

### Scope actually inspected

I inspected the supplied released-source anchor, **`7bebe7f46b50204834a18717b2d6d731a6cd27ca`**, including:

`allowance_windows.py`, `allowance_models.py`, `allowance_queries.py`, `allowance_index.py`, the reporting functions in `report_allowance.py`, and ADR 0044. I additionally inspected `allowance_schema.py` and lines 1–220 of `ledger_schema.py` to examine provenance and cache structure.

I read both proposal documents at **`73a887d8efd32e0c0cb6105fe4d5221ffd46f19a`**. The plan is explicitly proposed rather than released. :chatgpt-content-reference{index="0"}

The numerical results below are **executed synthetic experiments**, not validation on your ledger. No extension implementation was changed.

---

## 1. Repository findings that should change the proposal

### A. Reusing released segmentation does not, by itself, guarantee “never fit across resets”

**Repository fact.** In `allowance_windows.py::boundary`, a decrease satisfying `0 < drop <= 1` immediately returns `"correction"`. This happens **before** checking whether the previous reset time was crossed, the reset timestamp advanced, or reset credits decreased. 

Consider this synthetic pair:

| Field | Previous observation | Current observation |
|---|---:|---:|
| Observation time | 0 seconds | 900 seconds |
| Used percentage | 30.0 | 29.5 |
| Reset timestamp | 600 seconds | 605,700 seconds |
| Reset credits | 1 | 0 |

The function returns **correction**, despite both scheduled-reset evidence and a credit decrease.

A small *net* drop does not establish that little happened between captures. A reset followed by substantial consumption can produce a small drop—or no drop.

**Change:** require a forecast-safety check for conflicting reset and correction evidence. Do not forecast across this example. Either correct the shared boundary contract under separate regression tests or refuse the affected forecast until sufficient coherent post-boundary evidence exists. Do not silently change historical dollar estimates as a side effect of adding pace.

### B. Segmentation must be computed from the information available at the forecast origin

**Repository fact.** `allowance_windows.py::_identity_plans` resolves unknown runs using neighboring known plans, including later observations. `_build_from_costs` currently loads the observations and then calls `segment_windows(points)`.  

For example:

```text
Available prefix:     ["pro", "", ""]
Resolved identities:  ["pro", "pro", "pro"]

With a later sample:  ["pro", "", "", "plus"]
Resolved identities:  ["pro", "", "", "plus"]
```

This is reasonable retrospective reconciliation. It is not an as-of forecast replay.

**Change:** filter the evidence universe before deriving plan identity and segment membership. Filtering points after selecting a retrospectively constructed segment is insufficient. Future information can affect both accuracy and availability, not necessarily in an optimistic direction.

### C. Preserve the difference between deterministic ordering and trustworthy evidence

**Repository fact.** `segment_windows` marks unequal percentages at the same timestamp as ambiguous and skips the later point. However, `_build_from_costs` does not serialize `window.ambiguous` into the report-window dictionary. It includes corrections and closure, but not this ambiguity flag.  

Consequently, a forecast helper consuming only the current report dictionaries cannot fully recover the segmenter’s evidence assessment. A latest live anchor may also be the conflicting point that was skipped.

**Change:** retain sufficient ambiguity information and verify exact anchor membership. Do not average contradictory same-time readings merely to obtain a usable sample.

However, **do not blanket-suppress every segment marked ambiguous**. The flag also covers an unknown reset cause. A clearly separated post-reset sequence can support pace even when the cause of its starting boundary is unknown. Localize uncertainty to the affected boundary or observations.

### D. Forecast replay needs provenance that the display labels do not provide

**Repository facts.**

`allowance_status` identifies active buckets through `quota_provenance.provenance = 'live'`. By contrast, `_build_from_costs` labels points “Recovered” or “Captured” according to whether `timestamps_blob` exists. The latter is not an equivalent live-RPC provenance test. 

The quota schema stores observation timestamps and provenance links, but does not contain a per-recovered-observation first-available timestamp. Thus, these tables alone do not establish when every historical parsed sample became available. 

**Change:** preserve actual source provenance for fitting and evaluation. A final ledger snapshot is not automatically a leakage-free historical replay dataset. Where availability cannot be reconstructed, use live-read history for strict replay and label mixed-source retrospective experiments separately.

### E. The cache architecture is suitable, but freshness needs a separate forecast contract

**Repository facts.** `indexed_allowance_report` caches by ledger revision, pricing/index revision, and coverage, then refreshes status. Its index revision is incorporated into the pricing revision, so advancing it can invalidate event costs. Existing status freshness uses a one-hour age threshold, while the proposal specifies thirty minutes for forecasts. The renderer already exposes the successful observation time and last-known/partial status.   

**Keep** the ledger-only, disposable-cache architecture described in ADR 0044. **Change** forecast presentation eligibility independently of the existing meter’s freshness label. Measure any one-time repricing caused by revision invalidation rather than counting only warm fitting time. 

---

## 2. Strongest synthetic counterexamples

The checks are reproducible with standard-library Python:

:chatgpt-content-reference{index="14"}[Executable synthetic checks](sandbox:/mnt/data/quota_forecast_synthetic_checks.py) · :chatgpt-content-reference{index="15"}[Executed results](sandbox:/mnt/data/quota_forecast_synthetic_results.txt)

### A. Cumulative regression estimates a trend, not the elapsed-time average rate

Take five observations at minutes **0, 15, 30, 45, 60**. All these cases have ten percentage points of net movement, the same final balance, and adequate proposed recent coverage.

| Synthetic used percentages | Level-regression slope, pp/hour | Net change/hour | Regression exhaustion estimate, with 10 pp remaining |
|---|---:|---:|---:|
| 80, 82.5, 85, 87.5, 90 | 10 | 10 | 60 minutes |
| 80, 90, 90, 90, 90 | 8 | 10 | 75 minutes |
| 80, 80, 90, 90, 90 | 12 | 10 | 50 minutes |
| 80, 80, 80, 80, 90 | 8 | 10 | 75 minutes |

The difference is structural, not a numerical bug.

For continuous, uniformly sampled observations over a horizon \(H\), ordinary regression on cumulative usage implies:

\[
\hat r_{\text{level}}
=
\int_0^H
\underbrace{\frac{6s(H-s)}{H^3}}_{\text{weight on consumption at time }s}
r(s)\,ds.
\]

Consumption near the middle receives more influence; consumption near either endpoint receives less. The desired wall-clock average instead uses a constant weight \(1/H\).

**Implication:** “the trend in cumulative readings continues” and “the average consumption rate continues” are different contracts. Regression is not inherently invalid, but the UI should not quietly treat them as interchangeable.

### B. A six-hour half-life on levels is not a six-hour half-life on consumption rates

In a synthetic daily sequence sampled every fifteen minutes, consumption is:

- 1 pp/hour for twenty-one hours;
- 8 pp/hour for the newest three hours;
- final used percentage: 85%.

The executed results are:

| Estimator | Estimated rate, pp/hour | Estimated time until exhaustion | Outcome with reset in five hours |
|---|---:|---:|---|
| Proposed daily weighted level regression | 1.662 | 9.02 hours | About 6.69% remains |
| Direct exponentially weighted interval rate, six-hour half-life | 3.187 | 4.71 hours | Exhaustion before reset |
| Unweighted daily net rate | 1.875 | 8.00 hours | About 5.63% remains |

For the proposed weighted regression, the newest three hours contribute only **9.46% of the implied interval-rate weight** in this sampling arrangement. The implied mean age of consumption influence is about **9.70 hours**.

This does not prove that the interval estimator forecasts future behavior better. It does show that the six-hour parameter has a less intuitive effect than the proposal suggests.

**Test:** weight interval consumption directly when recency weighting is intended. Do not justify weighted level regression solely by naming its observation-weight half-life.

### C. Median buckets can erase the latest live movement

Synthetic observations remain at 80% at minutes:

```text
0, 15, 30, 45, 55, 56, 57, 58, 59
```

The latest live observation at **59.9 minutes** reports 90%.

The final five-minute bucket has median percentage 80%. After bucketing, every percentage is 80%, so the fitted slope is **zero**. Anchoring the projection at the live 90% cannot rescue a slope that discarded the change.

The raw endpoint rate is approximately **10.02 pp/hour**.

This example does not establish that the jump should be projected indefinitely. It establishes that the baseline’s regression evidence and projection anchor can describe different trajectories.

**Change:** retain the exact live anchor as an actual fit observation. For a bucketed regression, replace the final bucket’s representative with the anchor rather than appending it and giving that bucket extra weight.

Separate marginal medians also need caution around corrections: the median timestamp and median percentage need not be an observed pair.

### D. One sample per occupied bucket does not eliminate sampling-density influence

For the same underlying jump from 80% to 90% at minute thirty:

| Sampling arrangement | Regression slope, pp/hour |
|---|---:|
| Fifteen-minute captures | 12.000 |
| Additional five-minute captures before the jump | 13.000 |
| Additional five-minute captures after the jump | 11.667 |
| Five-minute captures throughout | 13.846 |

Every occupied bucket still contributes only one point. The net endpoint rate remains **10 pp/hour** throughout.

Bucketing limits replication *within* a bucket. It does not make densely observed portions of the hour and sparsely observed portions represent equal elapsed exposure.

Some extra observations genuinely improve knowledge of burst timing. The problem is claiming density invariance when the estimator is intentionally sensitive to those observations.

### E. Two percentage points is neither a general precision guarantee nor a relevance threshold

A synthetic sequence rises linearly from **98.5% to 99.5% over one hour**. Its rate is 1 pp/hour and its conditional exhaustion time is thirty minutes. The proposed movement gate suppresses it.

Conversely, under an explicit nearest-integer rounding assumption, endpoint errors can alter measured movement by up to one percentage point. A two-point observed change can therefore have substantial relative uncertainty.

For the net-rate estimator, assume only that endpoint rounding errors are bounded by \(q/2\). With observed span \(S\) and reset horizon \(D\), the rounding-only bound on projected used percentage is:

\[
|\text{projection error}|
\leq
\frac q2+\frac{qD}{S}.
\]

With \(q=1\) pp, \(S=1\) hour, and \(D=24\) hours, that bound is **24.5 pp**.

This is a deterministic sensitivity calculation—not a confidence interval. It excludes delayed reporting, corrections, changing workloads, and reset uncertainty.

**Implication:** minimum movement must be evaluated jointly with remaining quota, measurement resolution, and extrapolation horizon. Decimal formatting does not establish a reliable value of \(q\).

### F. Differencing and robust fitting have their own failure modes

For readings:

```text
50, 51, 50, 51, 50
```

the signed net rate is zero. Summing only positive increments invents **2 pp/hour** of consumption.

Likewise, a Theil–Sen median pairwise slope is zero for both the early-burst and late-burst examples above. A real burst followed or preceded by a plateau can look like an outlier to a robust trend estimator.

There is also a control favorable to ordinary regression. For a true constant rate of **2.3 pp/hour**, five quarter-hour observations, integer rounding, and 1,000 equally spaced starting fractional phases:

| Estimator | Synthetic slope RMSE |
|---|---:|
| Level regression | 0.355 pp/hour |
| Endpoint net rate | 0.458 pp/hour |

**Conclusion:** regression can reduce endpoint quantization error. Simplicity does not make the net-rate alternative universally more accurate.

### G. Delayed updates create an identification limit that no proposed estimator fixes

The observed sequence:

```text
80, 80, 80, 80, 90
```

could represent a genuine late burst, or steady consumption whose reporting was delayed until the final capture. A successful, recent RPC does not distinguish these worlds.

A fresh capture therefore establishes **fresh retrieval of a reading**, not necessarily fresh measurement of underlying consumption. Do not infer “observed idle” as confirmed zero consumption merely because rounded readings repeat.

---

## 3. Method comparison and exact estimators

Let eligible observations be \((t_i,u_i)\), with times measured in hours. The latest live anchor is \((t_n,u_n)\).

| Method | What it estimates well | Main weakness | Disposition |
|---|---|---|---|
| Proposed level OLS/WLS | Approximately linear cumulative trends with noisy readings | Implicit rate weighting, burst-position sensitivity, occupied-bucket density influence | Retain as a serious contender |
| Duration-weighted signed interval mean | Average net meter movement per elapsed hour | Endpoint noise and corrections; rectangular-window lag | Preferred simple reference |
| Direct exponentially weighted interval mean | Explicitly recency-weighted consumption pace | Greater sensitivity to recent reporting jumps; within-gap timing assumption | Daily challenger |
| Theil–Sen slope | Resistance to isolated erroneous observations | Can reject legitimate bursts and return zero across plateaus | Synthetic robustness check, not default |

### Proposed level regression

\[
\hat r_{\mathrm{level}}
=
\frac{\sum_i w_i(t_i-\bar t_w)(u_i-\bar u_w)}
     {\sum_i w_i(t_i-\bar t_w)^2}.
\]

Recent \(w_i=1\); proposed daily \(w_i=2^{-(t_n-t_i)/6}\).

Correlated cumulative deviations and repeated rounded readings do not make the slope unusable. They do make ordinary independent-error significance or confidence calculations inappropriate without a defensible observation model.

### Alternative 1: duration-weighted interval mean

\[
r_i=\frac{u_i-u_{i-1}}{t_i-t_{i-1}},
\]

\[
\hat r_{\mathrm{net}}
=
\frac{\sum_i (t_i-t_{i-1})r_i}
     {\sum_i(t_i-t_{i-1})}
=
\frac{u_n-u_0}{t_n-t_0}.
\]

This telescoping identity is valuable. Interior sampling density cannot change the estimate when endpoints remain fixed.

It does **not** assume uniform consumption inside each interval. It measures the interval’s average. It also does not establish that no reset occurred inside a gap; that remains an eligibility question.

### Alternative 2: direct exponential weighting of interval rates

For half-life \(h=6\) hours, let \(k=\ln 2/h\). Define elapsed-exposure weight:

\[
A_i
=
\int_{t_{i-1}}^{t_i}e^{k(s-t_n)}\,ds
=
\frac{e^{k(t_i-t_n)}-e^{k(t_{i-1}-t_n)}}{k}.
\]

Then:

\[
\hat r_{\mathrm{EW}}
=
\frac{\sum_i A_i r_i}{\sum_i A_i}.
\]

This weights **rates over elapsed time**, rather than treating each interval equally.

Unlike the unweighted net rate, this calculation assumes a rate allocation within each interval—here, constant rate. Longer gaps make that assumption more consequential. Do not bridge unacceptable gaps, drop their durations, and present the result as a full wall-clock daily pace.

---

## 4. Proposed calculation and eligibility contract

### Inputs and anchoring — **Change**

Use the already-loaded observations, but retain source provenance and ambiguity information.

Construct the evidence prefix available at the forecast decision. Exclude observations after the live anchor before resolving identity and segmentation. Select the same limit, duration, and compatible plan identity without borrowing from another segment.

Use only observations inside the named lookback. The starting endpoint should be an actual eligible observation; do not fabricate a sample at exactly sixty minutes or twenty-four hours ago. Preserve the exact latest live observation as the ending endpoint.

Calculate coverage and gaps from the canonical observations **before median bucketing**. Otherwise, bucket representative shifts can make an unchanged capture history pass or fail a gap threshold.

Do not clip negative increments, monotonize readings, or interpret reset-credit counts as extra quota. Small corrections require explicit diagnostics; incompatible rebasing or reset evidence requires refusal or a coherent post-change suffix.

### Parameters for the first comparison — **Test**

Keep these fixed initially so the estimator comparison is not confounded by gate tuning:

| Parameter | Recent | Daily |
|---|---:|---:|
| Lookback | 60 minutes | 24 hours |
| Proposed regression buckets | 5 minutes | 15 minutes |
| Proposed regression weighting | Equal | Six-hour half-life |
| Net-rate reference | Signed net change / elapsed time | Signed net change / elapsed time |
| Direct interval-weighted challenger | Not necessary initially | Six-hour half-life |
| Minimum distinct observation times | 3 | 5 |
| Minimum actual span | 30 minutes | 3 hours |
| Maximum adjacent gap | 30 minutes | 3 hours |
| Initial movement gate | Net increase ≥2 pp | Net increase ≥2 pp |

These are **reproducible starting settings, not validated acceptance criteria**.

In particular, define “movement” as net endpoint movement for this comparison, not an unspecified maximum-minus-minimum range that can be satisfied by a correction.

Then test movement thresholds and a precision-aware alternative separately. Do not replace the current arbitrary threshold with an equally unsupported collection of new thresholds.

### Actual coverage must be visible — **Change**

Three hours of current-cycle history is not a measured day. Keeping the twenty-four-hour *lookback* is fine, but burying actual coverage solely in diagnostics invites a stronger interpretation.

For example:

> **Daily pace · 3h observed:** If this pace continues, …

This preserves two rows and makes startup or post-reset truncation visible. A twenty-four-hour lookback is a maximum history window, not a promise that twenty-four hours were observed.

### Projection and reset comparison — **Keep**

Let:

\[
Q=100-u_n,\qquad D=R-t_n,
\]

where \(R\) is the reset timestamp captured with the active bucket and all times here are in hours.

For a supported positive rate:

\[
T_{\mathrm{exhaust}}=t_n+\frac Q{\hat r},
\]

\[
M_{\mathrm{reset}}=Q-\hat rD.
\]

Use unrounded values for classification:

- \(M_{\mathrm{reset}}>0\): projected quota remains at reset.
- \(M_{\mathrm{reset}}\leq0\): projected exhaustion occurs by reset.
- \(|T_{\mathrm{exhaust}}-R|\leq15\) minutes: “near reset.”

The reset is the **scheduled reset known at capture**, not a guaranteed future event. A later banked or global reset changes the conditions of the projection.

Anchor the balance to the live reading rather than the regression intercept. The intercept is not a better substitute for the observed quota state.

### Freshness and expired projections — **Change**

Retain the proposed thirty-minute forecast freshness ceiling, suppression after failed probes, and bucket-specific handling of partial responses. Those are already explicit in the proposal. :chatgpt-content-reference{index="12"}

Add an overlooked boundary: **the projected exhaustion time itself**.

A forecast captured twenty minutes ago may have predicted exhaustion ten minutes ago while still satisfying the thirty-minute freshness gate. Do not keep presenting that as an actionable future forecast, or infer actual exhaustion from it.

At rendering or cache retrieval, expire actionable forecast presentation at the earliest relevant boundary:

\[
\min(t_n+30\text{ minutes},\ R,\ T_{\mathrm{exhaust}})
\]

when exhaustion was projected before reset.

Show an awaiting-fresh-reading state after that boundary. A script-free page already open in a browser cannot be assumed to update itself; the observation timestamp must remain visible.

Once the exact live anchor is retained in the fit, the “last fit sample within twenty minutes of anchor” condition becomes redundant. The preceding gap and overall coverage still matter.

### Wording and uncertainty — **Keep, with a small Change**

Prefer:

> **Recent pace:** If this pace continues, quota would run out around 18:15.

> **Daily pace:** If this pace continues, about 12% would remain at reset.

Do not let “expected to last” stand alone as reassurance.

Keep point estimates rather than introducing an uncalibrated range. A rounding or parameter-sensitivity range may be useful in diagnostics, but it is not a probability interval. Where modest, explicitly assumed measurement perturbations reverse an individual row’s reset outcome, an “outcome unclear at this resolution” state is more honest than a precise surplus.

Do not suppress or combine the rows merely because they disagree. They represent different continuation assumptions, not two estimates of the same confidence interval.

---

## 5. Minimal leakage-free validation plan

### A. One bounded estimator comparison, not a broad tuning project

Compare the proposed baseline, net-rate reference, and direct exponentially weighted daily challenger with the initial gates held fixed.

Include the synthetic cases above plus steady burn, step-down to idle, rounded staircases, delayed batches, endpoint corrections, missing captures, same-time conflicts, and reset/plan transitions. Test small timestamp and bucket-phase shifts, duplication within buckets, and additional interior sampling.

Theil–Sen need not enter the historical selection exercise unless isolated bad observations are shown to be a material problem.

### B. Replay what was actually knowable

Use one forecast origin per live bucket reading. At each origin, include only evidence available then, and recompute identity and segmentation from that prefix.

Do not use later samples to resolve unknown plans, recognize a reset, choose a “clean” segment, or retrospectively select a favorable starting point.

For recovered samples, verify whether existing records can reconstruct availability. If not, conduct strict live-only replay using live-read provenance and treat mixed-source final-ledger analysis as a separate retrospective sensitivity exercise—not an online backtest.

Split chronologically, preferably at cycle boundaries. Choose parameters on earlier cycles, freeze them, and report later-cycle results. Random observation splits would share overlapping histories and future regimes.

### C. Define observable outcomes before scoring

**Exhaustion time is often interval-censored.** A last reading below 100% followed by a reading at 100% does not establish an exact crossing time. Delayed or rounded reporting further limits what can be claimed about actual task blocking.

Score against an evidence-supported crossing interval where appropriate; do not manufacture an exact timestamp by linear interpolation.

**Absence of a recorded 100% reading does not prove survival.** A reset followed by a low reading could conceal exhaustion during a gap. Distinguish observed exhaustion, observed reset without recorded exhaustion, and indeterminate outcomes. Any broader “survived” label needs an explicit coverage assumption.

**Unexpected resets are competing events.** A banked reset should not turn an impending-exhaustion forecast into a scored false alarm simply because the user intervened. Evaluate the original captured-deadline condition separately from realized outcomes after material deadline changes.

Similarly, do not score remaining quota “at reset” using a reading from substantially earlier without exposing that timestamp difference.

### D. Report four metric families together

| Family | Minimum reporting |
|---|---|
| **Exhaustion error** | Signed timing error, median and tail absolute error, or distance to an observable crossing interval; stratified by remaining quota and forecast horizon |
| **Reset-outcome classification** | False reassurance and false alarm separately; near-reset, indeterminate, and abstention counts retained |
| **Availability** | Fraction of all bucket-origin opportunities producing a forecast; reasons for suppression; availability near exhaustion and during post-reset startup |
| **Update stability** | Change in absolute predicted exhaustion time, reset-balance changes, outcome flips, and available/unavailable toggles |

Measure stability in **absolute exhaustion time**, not merely “hours remaining,” which should decrease as time passes.

Stratify at least by low remaining quota, short versus long extrapolation, partial-day coverage, large gaps, corrections, and workload changes. Report per-cycle as well as per-origin results so dense active periods do not dominate.

An estimator that achieves low error by withholding nearly all forecasts is not necessarily useful. Conversely, high availability obtained by issuing false-safe “quota remains” messages is not a successful result.

### E. Keep engineering acceptance separate

Use pure-function tests for estimator arithmetic and prefix segmentation. Use an injected clock for freshness, reset crossing, and already-passed predicted exhaustion. Verify indexed/full-path agreement and that no report request adds capture, source scanning, or pricing calls.

Benchmark on the authorized disposable ledger copy. I have **not** verified the twenty-millisecond target, historical availability, or operational forecast accuracy.

Choose the simplest estimator that offers an acceptable error–availability tradeoff on frozen evaluation data. A smaller timing error alone should not outweigh worse false reassurance or substantially reduced availability.

---

## Keep / Change / Test summary

| Classification | Decision |
|---|---|
| **Keep** | Two independent conditional rows; quota percentages rather than dollars/tokens; live balance anchoring; captured reset deadline; no invented gap samples; no active-work-only rate; cached ledger-only computation; coarse display rounding |
| **Change** | Prefix-before-segmentation processing; reset/correction conflict handling; preserved provenance and localized ambiguity; exact live anchor retained in fitting; actual partial coverage visible; expiry when predicted exhaustion has passed |
| **Test** | Level regression versus net wall-clock rate; direct exponential interval weighting; median representatives; six-hour half-life; movement/span/gap gates; correction handling; measurement-sensitive reset-outcome abstention |

**The smallest justified next step is an offline, provenance-correct comparison after fixing those contract holes—not additional forecasting machinery. The current evidence supports challenging the proposed estimator, but not claiming that any alternative has already demonstrated superior real-world forecasts.**