# Dashboard Preparation: Allocation And CSV Follow-up

Date: 2026-10-22. Local source candidate, not released or installed.

## Scope And Authority

The owner requested continued optimization toward post-capture Today <=3s and
first 30 days <=5s, including the first pass's CSV regression. This comparison
uses the completed first-pass candidate as its baseline. It does not compare
new timings directly with the earlier 12.66s sample block on different input.

The new mode=ro SQLite backup contains 880,416 usage events, 351,429 stored quota
rows, and 2,057,842,688 bytes. SHA-256:
`c86883334884b90d5702aedb0c8f0efa507313df8b0b84d309fa1ab828d929fe`.
The 30-day selection contains 200,572 events, 421 distinct contexts and 1,659
sources. Fixed clock is 2026-10-22T15:34:00+00:00, America/Toronto.

Private evidence: `output/performance/dashboard-preparation-followup-20261022/`.
The harness denies original-session access, external database access, networking
and subprocesses. Only disposable copies are written. At most one frozen ledger
and one working copy exist; the 6 GiB budget is unchanged. Live data, the retained
rollback archive, normal VS Code and hosted CI are outside this work.

## Diagnosis And Changes

- A retained-quota eviction ablation used identical code/input on both sides,
  clearing only the optional raw/pace memo before CSV on the candidate side.
  One preparation pair and one reversed measured pair retained identical CSV.
  Measured exports were 3.273/3.203/3.120s with retention and
  3.053/2.933/3.082s after eviction. This supports a retention cost, not a claim
  that all export time is GC or that all variation has been explained.
  Eviction itself took 55-70ms, separately recorded rather than hidden in CSV
  timing. That diagnostic block used 15:30 UTC on both sides; it is not mixed
  with the primary 15:34 UTC samples.
- Share immutable provenance labels rather than retaining hundreds of thousands
  of equal sets. Share scalar schemas instead of retaining one tuple per field
  per capture. Codec keys still distinguish JSON numeric types and signed zero.
- Build pace inputs once per request, with all-duration plan events. Share
  repeated immutable checkpoints, preserve every origin, and retain no new
  cross-capture boundary state. Reuse the primary-series reset membership index.
- Detect chart boundaries directly rather than computing/discarding extrema
  first. Track the first simultaneous signature plus a conflict flag instead of
  a set per timestamp. No observations, boundary neighbors or conflicts are lost.
- Stream SQL rows and reuse immutable normalized context metadata and source
  Paths within each query. The old path decoded 200,572 context JSON values for
  421 contexts and retained both the full SQL row list and records.
- Reduce the optional cross-request raw/pace memo limit from 500,000 to 50,000
  expanded points. Larger histories still prepare fully within the request;
  persisted report and fit caches are unchanged. This bounds retention rather
  than changing global GC settings or dropping evidence.

The first allocation-only pilot did not consistently improve the primary
timings. Its evidence is retained as `iteration1-pair`, not presented as a win.
The final candidate adds row streaming, the smaller retention budget, direct
boundary detection and shared pace states. No further persistent cache or
incremental reset-boundary algorithm was introduced.

## Verification

- Full Python suite: 3,312 passed, 1 existing skip (127.85s).
- Ruff and whitespace checks passed.
- Exact monetary/image/repository parity passed, including the indexed/full
  estimator comparison. Snapshot hash remains
  `58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`.
- Bounded-work check: zero language repricing for quota-only changes and zero
  unchanged speed-recovery source opens.
- Breakdown browser check: 720 views across Chromium, WebKit and Firefox,
  including dense history, DST, conflicts and script-disabled navigation.
- Independent read-only review found no actionable issue. Added direct
  old-reducer/new-boundary parity for duplicate/pre-annotated readings and DST,
  plus query-local metadata correction/rollback and sharing tests.
- One broad-suite failure was a removed instrumentation import. Its guard now
  forbids both the new input constructor and preparation method; the subsequent
  full suite passed. An initial missing SQL column in Path memoization was fixed
  by using the exact returned file path, then verified by row-level parity.

## Measurement Protocol

`scripts/benchmark_collector.py --mode report --workload dashboard-csv` runs
Today, first 30 days, cached views, a disposable usage/quota append, both views
after append, and complete CSV export. Five alternating measured pairs follow
one excluded preparation pair. No profiler or GC callback is active in that
block. Tests/browser runs finish before it starts. All exact HTML/CSV hashes,
source/harness identities, dependencies, wall/CPU times, writer duration,
database/WAL sizes and peak RSS are retained in `final-pairs/evidence.json`.

This is a backend source comparison, not packaged startup, HTTP transport or
WebView paint acceptance. External machine load is not controlled; retain every
sample and report ranges, not p95 claims. The first-pass ten-pair result remains
historical; this shorter follow-up is five pairs, not a replacement ten-pair run.

## Matched Results

All five measured pairs preserved every HTML hash and the full 1,925-row CSV.
One preparation pair was excluded as planned; no slow sample was discarded.
Ranges below are observed minima/maxima, not confidence intervals.

| Operation | First-pass median (range), seconds | New median (range), seconds |
| --- | --- | --- |
| First Today after revision | 11.24 (10.91-11.79) | 9.87 (9.26-10.53) |
| First 30 days | 13.72 (12.55-14.42) | 10.35 (9.69-10.80) |
| Today after usage/quota append | 12.77 (11.15-14.03) | 8.86 (8.52-9.96) |
| 30 days after append | 12.14 (10.41-14.78) | 8.81 (8.18-9.87) |
| Complete 30-day CSV | 3.79 (3.28-4.04) | 2.37 (2.25-2.68) |
| Cached Today | 0.361 (0.081-0.365) | 0.080 (0.075-0.092) |
| Cached 30 days | 0.095 (0.091-0.126) | 0.089 (0.085-0.092) |

Today after append improves 31%, first 30 days 25%, 30 days after append 27%,
and CSV 38%. The CSV slowdown is reversed on this workload. Peak RSS across
measured samples falls from 1.583 GB to 1.165 GB (26%). Maximum recorded database
and sidecar size remains 2.106 GB. Post-append allowance writer ownership is
0.599 -> 0.279s median. This is not a live capture-duration measurement.

The 30-day HTML remains exactly 15,630,561 bytes before append. No rows or chart
evidence were deleted to achieve these results. Large-history quota retention
is 387,790 -> 0 points across requests; persisted data remains complete.

**The 3s/5s targets are still unmet.** Today after capture remains 5.86s over its
target, and first 30 days 5.35s over. This pass improves preparation cost and
export behavior but still rebuilds full quota structure after quota changes.
It must not be described as completed incremental history preparation.

Source-set hashes (same relative-file/hash-map method as the first pass):

- Baseline: `a1f2a899f55f9ef58309dccddb58a73523d13e9d10259999cf9bc7a9876d425b`.
- Candidate: `c3b3eadde3199fd502b868da998b591c681d955995850724b33c4cd8fa2e1256`.
- Harness: `effcc5bfc6c0222c3f8b618e325fd8386fee7798fa9b1493a022e2716d36fa72`.
- Python 3.13.12 / SQLite 3.50.4; dependency versions retained with each pair.

## Remaining Profile And Handoff

The final candidate profile uses the same frozen input but is separate from
adoption timings. First Today records 62.98s cumulative in allowance preparation
out of 71.86s profiled CPU. Display history, pace, reset periods and encoding
still consume whole-history input; the codec visits 357,454 capture keys.
The new scalar-key loops are particularly amplified by Python call tracing.
Do not subtract these cumulative times or treat them as wall-time forecasts.

First 30 days records 49.59s profiled CPU: valuation 9.29s, project economics
8.05s, and 29 daily capture partitions 9.04s (nested, not additive). It constructs
267,744 display points. Row materialization now calls the decoder 200,572 times
but shares the 421 contexts; query time is 3.57s profiled. Event-time API/credit
selection still occurs 401,144 times. Profiles are retained under
`candidate-profile/` for the next bounded comparison.

The next substantial work is dependency-aware reuse of unchanged history and
daily display components, with exact invalidation for corrections, provenance,
cross-duration plan changes, simultaneous conflicts and boundary neighbors.
Completed monetary fits alone are not sufficient authority for display or pace
continuity. Selected-record pricing and turn metrics are a separate remaining
30-day cost. No incremental boundary algorithm or new event store is claimed in
this candidate; no benchmark justifies a runtime/language replacement here.

The large frozen input and all working database copies were removed after the
final hash check. Compact source snapshots, JSON measurements, profiles and
synthetic browser evidence remain. No CI, commit, push, release, installation,
normal VS Code activation or live-ledger change was performed.
