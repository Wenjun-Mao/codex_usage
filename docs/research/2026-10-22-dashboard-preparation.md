# Dashboard Preparation: Local Qualification

Date: 2026-10-22. Status: bounded local implementation and verification complete;
performance targets remain unmet. Not released or installed.

This records the first pass. Continued allocation, row-materialization and CSV
work is recorded separately in the
[follow-up](2026-10-22-dashboard-preparation-followup.md), with a fresh matched
input rather than overwriting these measurements.

## Authority And Boundaries

Implementation follows the approved
[plan](../plans/dashboard-preparation-performance.md) and
[ADR 0073](../adr/0073-snapshot-pinned-dashboard-preparation.md).
Baseline HEAD is `3c9326b217ca8fb5f64b2acf0a33f6ec7200ae0b`, with the
preexisting ADR 0072 writer-admission patch on both sides. The comparison does
not attribute that earlier correctness fix to this performance work.

One private, coherent read-only backup contains 879,412 usage events, 350,355
stored quota rows, and 2,057,842,688 bytes. Reports use disposable copies only,
with original-session/database access, networking and subprocesses denied by
the existing benchmark audit guard. Fixed clock: `2026-10-22T14:03:00+00:00`,
timezone America/Toronto. No live capture, account call, upload, normal VS Code
activation, installed-package change or hosted run was performed.

Private evidence is under
`output/performance/dashboard-preparation-20261022/`: the baseline manifest,
frozen source trees, diagnostic profiles and paired JSON results. The large input
backup and all working ledgers were removed after verification. Input SHA-256:
`f9e33b818ad06f65ebbdf7ce2957c8a01c1d32503a9f720d93e4bd03967384ee`.
The original primary harness is retained as `benchmark-primary.py`. Source hashes,
interpreter/SQLite versions, dependency versions and harness identity are retained
with the final samples. These source-only results are backend times, not packaged
collector startup, transport or WebView paint measurements.

Final source-set identities (SHA-256 of the sorted relative Python file/hash map):

- Baseline: `150dcfa8b1c7d627e5aac7e6e94e26958e167c40d4d118ba441a347729f9bf15`.
- Candidate: `a1f2a899f55f9ef58309dccddb58a73523d13e9d10259999cf9bc7a9876d425b`.
- Harness: `8bab2414e4b1bdf11d36b90a3150d64fa64ddd7e3d9bf982715bb736809c6c06`.
- Runtime: Python 3.13.12, SQLite 3.50.4; complete dependency versions in JSON.

## Primary Results

One preparation pair was excluded from the following ten alternating pairs.
Every compared HTML hash matched exactly; no failing or slow sample was removed.
Ranges are observed min-max, not confidence intervals or p95 estimates.

| Operation | Baseline median (range), seconds | Candidate median (range), seconds |
| --- | --- | --- |
| First Today after revision-only change | 12.15 (10.66-14.05) | 9.90 (9.35-18.95) |
| First Today -> 30 days | 20.87 (18.84-22.41) | 12.66 (11.74-15.17) |
| Cached Today | 0.104 (0.071-0.764) | 0.082 (0.073-0.830) |
| Cached 30 days | 0.088 (0.079-0.093) | 0.088 (0.081-0.104) |
| Disposable usage/quota append write | 0.081 (0.073-0.107) | 0.079 (0.072-0.105) |
| Today after that append | 12.32 (10.53-14.96) | 10.38 (9.43-12.27) |
| 30 days after that append | 20.37 (18.05-23.60) | 11.37 (9.82-13.93) |

First 30-day loading saves **8.21 seconds / 39%**. Ordinary post-capture Today
saves **1.94 seconds / 16%**. Post-capture 30-day loading saves **9.00 seconds /
44%**. The primary 50% reduction and 3s/5s engineering targets are **not met**.
Warm medians meet 500 ms, but Today has outliers over that target on both sides.
Later wall-time spikes also exceed parent CPU time; their exact scheduling/I/O
cause is not established. No extra favorable-sample block was run.

Ordinary post-capture allowance writer ownership falls **10.01 -> 0.313 seconds**
at the median (baseline range 8.54-11.79; candidate 0.20-0.72). Peak process RSS
across measured samples is 1.63 -> 1.61 GB. Maximum database/sidecar size recorded
after operations is 2.082 -> 2.100 GB; maximum allowance-publication WAL before
the reader closes is 95.65 -> 104.65 MB. The synthetic append write does not
regress, and the concurrency tests independently establish that capture need
not wait for pure report preparation. This is not an end-to-end live capture
benchmark.

## Root Causes And Changes

| Repeated work / owning layer | Change | Guardrail |
| --- | --- | --- |
| Millions of immutable total constructions in aggregation/economics | Request-local accumulators, frozen at existing boundaries | Original record order and every accounting component preserved exactly |
| Agent export structures built for a daily-only dashboard | Dedicated daily activity builder; full structures only for explicit export | Daily totals, ancestry, missing parents, cycles and DST parity |
| Repeated quota hashing, timestamp parsing and exported capture reconstruction | Derived scalar memos and one canonical capture directory | Evidence fields, codec identity and original dictionaries retain their semantics |
| Full history decoded for initial directory navigation | Separately versioned endpoint projection | Exact detail still uses full codec; malformed projection falls back |
| Unchanged raw quota and pace evidence rebuilt after usage-only revisions | One bounded immutable preparation keyed by independently tracked quota generation | Mode=ro pinned snapshots only; old-writer changes, repair and rollback tests |
| Pure allowance computation owns the writer | Read/compute first, revision-and-source-token-checked publication afterward | Concurrent capture can commit; stale publication and dirty-span consumption are rejected |
| Account-wide speed constructs unused ownership records | Read normalized model/task/time fields directly | Project filtering and transitions retain original path; sample populations unchanged |

The initial accumulator/daily-summary pass reduced a diagnostic first-30-day
load from 20.21 to 13.77 seconds. Later changes reduced it further. These staged
single-run observations locate gains, but final adoption comparisons use the
quiet paired measurements, not these pilots or profiler timings.

No persistent selected-event store, progressive UI, prewarming or incremental
reset-boundary segmentation was added. Quota changes conservatively rebuild the
quota component; only demonstrably unchanged raw/pace evidence is reused.

## Verification

- Full Python suite: **3,304 passed, 1 existing skip**.
- Extension build/tests: **86 passed**.
- Ruff and `git diff --check`: passed.
- Exact monetary/image/repository parity: passed; snapshot hash
  `58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`.
- Bounded-work checks: quota-only update caused zero language repricing;
  unchanged speed recovery opened no sources.
- Synthetic Chromium/WebKit/Firefox checks: allowance 216 state cases plus
  36 meter cases, economics 18 cases, speed 162 views, breakdown 720 views.
  Script-disabled history/navigation and responsive layouts remain covered.
- Independent read-only review completed. Fixed reset-history endpoint ownership
  and malformed optional-projection fallback, including cross-boundary indices.
- Source-backed pilot preserved every compared HTML byte across revision-only,
  first-30-day, cached ranges and real disposable usage/quota append scenarios.

## Cold Fill And Trade-offs

One preparation pair and one measured empty-account-cache pair produced identical
HTML. The measured cold Today load was **14.44 -> 11.29 seconds**; subsequent
Yesterday **1.36 -> 0.48 seconds**. These are supporting single-pair observations,
not ten-pair adoption statistics.

Allowance writer-context ownership fell **11.73 -> 0.98 seconds** for that cold
fill. This includes the publication transaction but is not a separate SQLite
BEGIN-to-COMMIT timer. Admission/setup was 2.9 -> 5.6 ms. Peak process RSS was
1.35 -> 1.34 GB; the preparation pair was 1.29 -> 1.36 GB. Staging every missing
price in memory did not cause material peak growth on this input. It is not a
fixed memory bound for arbitrarily larger cold ledgers; the ADR records a private
spooling follow-up if larger-scale evidence requires it.

The overview increased stored allowance payload from 94.44 to 103.37 MB on this
input. It avoids decoding the much larger exact-history payload on default
navigation, but is not free storage. Cache publication and long pinned readers
still write/retain WAL pages. Final samples record publication-held WAL and total
database bytes separately. Working copies are removed after each successful
benchmark block; the live ledger and retained rollback archive are untouched.

## Supporting Checks And Remaining Work

The extended block preserved exact HTML and the complete **1,902-row CSV**.
Its measured pair was: Yesterday 1.74 -> 0.59s, seven days 4.09 -> 1.97s,
30-day day theme 14.67 -> 7.91s, one-project selection 13.50 -> 10.60s, exact
history 2.21 -> 2.30s. These are supporting single-pair observations. CSV was
3.40 -> 4.27s, which prompted one bounded diagnostic follow-up. The excluded preparation pair had CSV
3.81 -> 3.64s; both pairs are retained.

That follow-up used one excluded preparation pair and three alternating measured
pairs, each exporting three times after preparing Today and 30 days. Its exact
1,902-row CSV matched throughout. Per-batch CSV medians were baseline
3.10/3.13/3.02s and candidate 3.16/3.88/3.32s; median of those batches was
**3.10 -> 3.32s (+7%, +0.22s)**. Observed median GC time per export was
0.48 -> 0.81s. The candidate retained 386,614 immutable quota points whereas the
baseline had no cross-request quota memo. This identifies a retention/GC cost to
investigate before increasing the cache budget; it is observational evidence,
not a causal eviction experiment. Do not claim exports became faster or that
the original slow sample was proved to be noise. No further timing block ran.

The final candidate profile identifies the remaining work:

- Today: full allowance preparation dominates (61.04s cumulative out of 70.83s
  profiled CPU). It includes display segmentation, pace preparation, reset
  periods and complete report encoding. A new quota reading still touches the
  full history; unchanged-fit reuse alone cannot remove this work.
- First 30 days: 199,568 selected events; materialization 20.04s, project
  economics 8.12s, breakdown time-view 19.04s and speed aggregation 3.92s
  cumulative profiled CPU out of 61.04s. Time-view preparation touches 29 daily
  capture partitions. These nested/instrumented values are attribution, not
  additive wall-time estimates.
- Exact 30-day HTML remains **15,522,422 bytes**, unchanged from the baseline.
  Transfer and WebView layout/paint have not been measured here. A smaller
  default payload would need a separate fidelity/accessibility contract, not
  silently deleting evidence or reducing the approved chart.

The final pairs establish that ordinary post-capture time remains above the
3-second target. The next measurable work is safe reuse of unchanged history/
display preparation plus reduced selected-record/pricing work, rather than a
runtime or language replacement inferred from these results.
The next architecture expansion must be justified by that measured gap, not
silently folded into this delivery. Native VS Code/packaged end-to-end acceptance
and publication require their own explicit owner request.

No additional history-partition persistence, SQL query-plan redesign, large
synthetic-scale acceptance fixture or native transport/paint qualification was
claimed. Late-correction/pricing/old-writer correctness is covered by the local
test matrix, not by a ten-pair real-data timing block for each mutation. These
remain explicit limits of this bounded checkpoint.

## Reproduction Entry Points

Use `scripts/benchmark_collector.py --mode report --workload dashboard` for the
primary protocol; `dashboard-extended` adds ranges, theme, filter, export and
history. `--account-mode empty` measures cold price/fit caches separately.
`--workload export-followup --trace-gc` is a diagnostic supporting block, not an
adoption timing substitute. Supply explicit frozen baseline/candidate source
directories, an approved private snapshot, fixed `--now`, fresh output directory
and `--repeats 10` for the primary protocol. Snapshot plus temporary copy and
retained evidence must fit the 6 GiB budget. The harness verifies exact HTML/CSV
hashes and deletes successful working copies; failed copies require inspection
and owned cleanup.

`scripts/profile_dashboard.py --account-mode revision --ranges today 30d` locates
remaining work without priming the allowance index. Keep profiled runs separate
from the unprofiled protocol. Browser evidence is synthetic and retained under
`output/playwright/dashboard-preparation-20261022/`.
