# Plan Allowance Historical Calibration

Date: 2026-09-21

## Purpose

Evaluate whether historical Codex rollout JSONLs contain enough trustworthy quota
snapshots to support a future Plan Allowance feature before defining its product
and storage contracts.

This was a read-only calibration. It did not modify rollout files, the durable
ledger, capture state, or product code.

## Conclusion

Historical recovery is partial overall, but recent weekly `codex` quota windows
contain enough observations to support qualified, workload-specific allowance
estimates.

The strongest completed weekly segment, September 12-19, supports a local
API-equivalent estimate near **$1,240 per 100% allowance**. This is not evidence
of a fixed account entitlement: older segments are incomplete, short windows are
not dependable, account-wide usage may exceed the local ledger, and model mix and
pricing change over time.

Recommended direction:

- Capture future quota snapshots directly from Codex App Server as authoritative
  observations.
- Permit bounded historical recovery with explicit `Recovered` provenance.
- Estimate each reset segment independently using multiple observations.
- Publish an estimate only when coverage and stability gates pass.
- Never present the estimate as cash value, a contractual allowance, or proof
  that OpenAI changed plan limits.

## Bounded Recovery

The calibration considered all 1,953 locally retained rollout files but avoided
reading large interiors:

| Measure | Result |
| --- | ---: |
| Corpus size | 24,784,236,034 bytes |
| Largest rollout | 9,452,453,014 bytes |
| Initial bounded reads | 252,985,613 bytes |
| Quota-field verification rereads | 7,152,225 bytes |
| Total rollout bytes read | 260,137,838 bytes |
| Share of corpus read | 1.05% |
| Files read completely | 112 |
| Files yielding quota snapshots | 1,946 |
| Raw snapshots | 8,821 |
| Deduplicated snapshots | 8,142 |

Files of at most 128 KiB were read completely. Larger files contributed at most
64 KiB from the beginning and 64 KiB from the end. Partial boundary rows were
discarded. The resulting recovery is intentionally endpoint-biased and must not
be described as complete history.

The read-only ledger export contained 250,675 trusted usage events. The SQLite
query incurred 12,851 page-cache misses, approximately 52.6 MB of logical page
fills, and zero page writes.

## Historical Coverage

- Quota snapshots covered 53 of 114 ledger-active days across the available
  history.
- August 25 through September 21 covered all 27 ledger-active days.
- The longest observation gap in that recent period was 47.2 hours.
- Daily presence does not prove that every reset boundary or account-wide use was
  observed.

All recovered snapshots used the same outer event shape:

```text
event_msg -> token_count -> rate_limits
```

Populated quota windows carried numeric `used_percent`, integer
`window_minutes`, and Unix-second `resets_at` values. No recovered percentage
fell outside 0-100.

Observed plan values were predominantly `pro`:

| Plan value | Snapshots |
| --- | ---: |
| `pro` | 8,767 |
| `plus` | 7 |
| `prolite` | 7 |
| unavailable | 40 |

Observed limit/window forms included:

| Limit | Slot | Duration | Observed period | Assessment |
| --- | --- | ---: | --- | --- |
| `codex` | primary | 300 minutes | Apr 21-Jul 18 | Partial; not dependable for allowance estimation |
| `codex` | secondary | 10,080 minutes | Apr 21-Jul 18 | Partial; not dependable for allowance estimation |
| `codex` | primary | 10,080 minutes | Jul 15-Sep 21 | Partial overall; qualified recent estimates possible |
| `codex_bengalfox` | primary | 300 or 10,080 minutes | Jul 21-Sep 17 | Constant 0%; not economically identifiable |
| `codex_bengalfox` | secondary | 10,080 minutes | Aug 29-Sep 17 | Constant 0%; not economically identifiable |
| `premium` | none populated | sample only | Unusable |

The weekly `codex` window moved from secondary to primary across historical
versions. Slot is therefore an observed attribute, not a durable identity by
itself.

## Reset Reconstruction

Snapshots were grouped by limit ID, slot, duration, and plan. Usage drops were
examined as candidate boundaries, with reset timestamps used as supporting
evidence rather than the sole window identity.

The calibration found 106 candidate segments and these boundary signals:

| Signal | Count |
| --- | ---: |
| Drop compatible with scheduled reset | 7 |
| Larger early or unknown drop | 52 |
| One-point correction candidate | 29 |
| Scheduled-time crossing without an observed drop | 6 |

Reset timestamps were not stable enough to identify windows alone. The recent
weekly-primary series contained 912 reset timestamp changes, including 884 within
60 seconds and 446 backward changes.

The calibration deliberately split at every decrease to expose anomalies. The
product implementation should be more conservative:

- Keep one-point drops inside the current segment as meter correction noise.
- Start a new segment for a material drop or corroborated reset transition.
- Record scheduled, early, manual/banked, global, correction, and unknown as
  evidence classifications; do not claim a cause that snapshots cannot prove.
- Treat the reported duration as descriptive metadata, not an assumption that
  every segment lasts exactly seven days.

## Economic Calibration

For each candidate segment, cumulative trusted ledger API-equivalent cost was
joined by timestamp and fitted against displayed percentage used:

```text
cumulative API-equivalent cost = intercept + slope * used percentage
estimated 100% allowance value = 100 * slope
```

The intercept allows observations to begin after the actual reset. Exact
timestamp/source matches were available for 7,543 of 8,821 raw snapshots. At the
deduplicated timestamp level, 7,207 of 8,142 snapshots matched a ledger event.

Forty-two segments passed a permissive screen of at least five observations, ten
percentage points, and positive cost. Only 17 also had no unpriced events and
coherent reset timestamps within 60 seconds.

Selected results:

| Segment | Observations | Span | Cost span | Fitted 100% value | Pairwise P10-P90 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jul 9-10, five-hour | 270 | 99 pp | $165.13 | $174.17 | $138-$211 |
| Jul 9-10, weekly secondary | 427 | 40 pp | $323.65 | $761.03 | $564-$948 |
| Sep 3-4, weekly primary | 388 | 37 pp | $590.75 | $1,741.11 | $1,665-$1,810 |
| Sep 8-9, weekly primary | 73 | 69 pp | $252.69 | $294.49 | $43-$345 |
| **Sep 12-19, weekly primary** | **1,434** | **99 pp** | **$1,253.99** | **$1,240.55** | **$1,216-$1,266** |
| Sep 19-21, ongoing weekly | 159 | 16 pp | $210.41 | $1,297.66 | $1,214-$1,403 |

The pairwise ranges are sensitivity diagnostics, not statistical confidence
intervals.

The September 12-19 segment was stable under selective review:

- 19,655 ledger events and no unpriced events.
- Regression R-squared of 0.9997.
- Percentage-bin regression of $1,240.68.
- Leave-one-day-out range of $1,235.63-$1,244.09.
- Restricting observations to 20-80% yielded $1,226.98.
- Endpoint estimate was $1,266.65.
- Shifting join timestamps by plus or minus 60 seconds changed the endpoint range
  only to $1,266.23-$1,267.46.

The ongoing September 19-21 segment is directionally consistent but spans only
16 percentage points and must remain provisional.

## Reliability Assessment

### Structural reliability: good

The quota records are structured producer events with a consistent outer schema.
Percentages, durations, reset times, plans, and bucket identifiers are available
without parsing user-visible text.

### Historical completeness: partial

Bounded endpoint sampling misses large-file interiors, deleted rollouts cannot be
recovered, and observation gaps can hide reset boundaries. Historical points
must retain recovery provenance and coverage metadata.

### Recent weekly economic reliability: qualified

Recent fully priced weekly segments can produce stable local API-equivalent
estimates when they span enough percentage points and pass sensitivity checks.
The September 12-19 segment is strong calibration evidence.

### Older and short-window economic reliability: poor

Across the full ledger, 50,267 events, or 20.1%, have unpriced model identities.
All April-June ledger events are unpriced. Historical five-hour and older weekly
results therefore cannot support dependable allowance claims.

## Required Release Gates

A future implementation should expose a window estimate only when all applicable
gates pass:

1. At least five distinct observation times and several distinct percentage
   levels.
2. A meaningful observed span, initially at least ten percentage points, with
   stricter confidence for prominent summaries.
3. No cross-segment negative consumption.
4. No material unpriced usage in the fitted interval.
5. Stable bucket, plan, and duration identity.
6. Acceptable fit and sensitivity diagnostics.
7. Explicit local-ledger coverage and source provenance.
8. Clear provisional treatment for incomplete or ongoing windows.

The UI should fold data in two levels: reset-window summaries first, then raw
captures within each window. Each summary should show observed dates, reported
duration, plan, bucket, percentage span, local cost span, estimate, quality, and
closure classification.

## Planning Implication

The evidence supports planning a Plan Allowance feature, including bounded
historical recovery. The plan must preserve raw observations so segmentation and
estimation methods can improve without rescanning source files. Future live
snapshots should be authoritative; historical recovered snapshots should remain
clearly distinguishable.
