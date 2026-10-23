# Serialization And Valuation Preparation

Date: 2026-10-22. Local candidate, not released or installed.

## Root Cause And Implementation

The previous post-append profile identified repeated canonical capture encoding,
per-response schedule binding and full-component aggregation inside turn metrics.
This pass applies [ADR 0075](../adr/0075-compact-allowance-captures-and-batch-valuation.md):

- Persist ordered capture field layouts once, followed by indexed value rows.
  Restore exact dictionaries, types, signed zero and shared capture ownership.
  Keep validation, including order-insensitive duplicate content checks.
- Bind each immutable API/credit schedule once per batch, retaining per-response
  event time, aliases and long-context selection. Share the unchanged arithmetic
  with scalar valuation; no cross-request priced-event cache.
- Accumulate only total USD and unpriced tokens for turn metrics. Start with the
  first response and add sequentially within each turn, preserving Python's
  builtin sum for the final turn/response populations. Full project/model totals
  still retain every accounting component in its original order.

No ledger/parser schema, population, rounding, pricing or UI text changed.

## Private Input And Method

One coherent SQLite mode=ro backup, 2,072,506,368 bytes; 881,929 usage events;
352,999 stored quota rows / 389,492 recorded samples. Latest endpoint is
2026-10-22 17:01:20.647316 UTC. Fixed clock: 17:02 UTC, America/Toronto.
Input SHA-256:
`3503944bf308feb4a8f5d86252cd3a66df47346c3a13cb63474a9c8ae9e29868`.
Python 3.13.12 / SQLite 3.50.4. Baseline is the preceding completed incremental
candidate frozen before edits. Do not compare timings directly with its older
snapshot. Existing writer admission and prior optimizations are on both sides.

Evidence root: `output/performance/dashboard-serialization-20261022/`.
Only one active working copy plus the frozen ledger; all mutations occur on
disposable copies. Report guards deny original source files, external databases,
network and subprocess execution. No raw logs, live capture, account calls,
private uploads, CI or native VS Code activation. Protected rollback untouched.

The initial `paired` preparation attempt stopped on raw HTML hash mismatch:
allowance history authorization scope includes the codec revision. It produced
no accepted timing pairs. The corrected harness retains raw hashes and permits
only normalization of validated, actually issued allowance-history scope hashes.
All navigation states, target indices, text, numbers and other HTML bytes must
still match. Tests prove that changed dollars/states or unissued scopes fail.
This comparison rule does not change product authorization or stale-link guards.

`diagnostic-layout-v1` retains the excluded preparation pair and one measured
pair from the first layout implementation. It was stopped before qualification
to remove repeated layout/type validation and duplicate tuple extraction.
Layout validation is now cached by immutable field names and actual value types;
per-capture content and duplicate checks remain. A small diagnostic measures
100,000 capture identity calls at 0.133s baseline / 0.060s candidate. This is a
microbenchmark, not a full-report adoption result. The original `candidate-src`
is retained for that diagnostic. `diagnostic-pre-upgrade-guard` retains the next
preparation/one measured pair before an upgrade regression was found. Final
source is `final-src`; neither diagnostic block is adoption evidence.

Final primary evidence in `qualified-pairs` is ten alternating unprofiled pairs after one excluded
preparation pair. Retain all samples and machine-load outliers. First 30 days
follows Today, so account-wide allowance preparation is already available.
The append is one synthetic usage event plus one new quota reading, not a full
live capture. Backend timings exclude WebView transfer and paint.

## Verification And Review

- Full Python run: 3,351 passed, one skip, one failed test that counted calls to
  the former pricing entrypoint. Updated instrumentation observes API/credit
  calculation plus unknown fallbacks and still checks one valuation per record
  after downstream consumers. The focused 44-test rerun passed.
- After the final layout refinement and benchmark comparison guard, the full
  Python suite passed: 3,353 passed, one existing skip, 101.73s.
- A subsequent end-to-end format 2 -> 3 regression test reproduced a cached-HTML
  upgrade failure: the base cache-hit branch discarded the rebuilt allowance
  report, and history rendering could not see its newly published row through
  the pinned older snapshot. The base renderer now passes that already prepared
  report onward. The upgrade and 29 related pricing/work tests pass, including
  a guard forbidding range revaluation. This guard was added after the full run.
  The reviewer subsequently checked this handoff and the final layout validation
  refinement, with no findings; that delta review ran no additional tests.
- Final full-suite rerun, after all product/tool/test edits: 3,354 passed, one
  existing skip, 94.18s. Ruff and diff whitespace checks also pass.
- Exact boundary tests compare batch/scalar valuation for every checked-in
  effective rate before/at/after launch, aliases and unknown models, both sides
  of the long-context threshold, mixed offsets, naive UTC, equal-date ties,
  unsorted schedules and independent schedule replacement.
- Exact turn tests include adversarial positive floating values, interleaving,
  blank IDs and partially priced mixed-model turns. Legacy fixed format 1/2
  payloads, numeric types/signed zero, reordered layouts, nested values and
  malformed layout/row/reference cases pass.
- Exact monetary/image/repository parity remains
  `58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`.
  Quota-only update reprices zero language events; unchanged recovery opens zero
  sources. Ruff and diff whitespace checks pass.
- Independent read-only review requested GPT-6.1 Sol / High (effective host
  settings unverified). It identified the same obsolete test instrumentation,
  independently verified the correction and found no remaining actionable issues.
  Reviewer evidence: 676 capture-identity comparisons and 60 exact economics
  comparisons, including float.hex(); these are not manager-run acceptance counts.
  A small synthetic memory probe found lower canonical encode peak but higher
  copied-point encode/decode peaks. Full workload RSS must be reported separately.
- No UI rendering code changed. This pass uses complete HTML comparisons and
  existing Python rendering tests; it does not claim a new browser/native run.

## Measurements

Ten final alternating pairs, with the preparation pair excluded in advance:

| Operation | Baseline median | Candidate median | Baseline range | Candidate range |
| --- | ---: | ---: | ---: | ---: |
| First Today after revision | 8.520s | 8.451s | 8.123-9.482s | 8.128-9.320s |
| First 30 days | 8.963s | 8.062s | 8.514-10.753s | 7.759-9.053s |
| Cached Today | 0.076s | 0.076s | 0.073-0.097s | 0.073-0.080s |
| Cached 30 days | 0.085s | 0.086s | 0.082-0.091s | 0.082-0.090s |
| Disposable append write | 0.074s | 0.072s | 0.071-0.080s | 0.066-0.076s |
| Today after usage/quota append | 8.271s | 8.120s | 7.889-9.271s | 7.737-8.423s |
| 30 days after usage/quota append | 7.330s | 6.718s | 7.153-7.958s | 6.618-6.932s |
| 30-day CSV | 2.142s | 2.158s | 2.116-2.245s | 2.100-2.301s |

First 30 days improves 10.1% (0.90s); post-append 30 days improves 8.3% (0.61s).
Today after append improves only 1.8% (0.15s); CSV changes by +16ms. No operation
regresses by both 10% and 100ms. Targets remain unmet: Today is 5.12s above 3s,
and first 30 days is 3.06s above 5s. Cached navigation stays below 500ms.

CPU medians: first Today 8.160 -> 8.266s, first 30 days 8.231 -> 7.645s,
post-append Today 7.797 -> 7.656s, post-append 30 days 7.269 -> 6.683s, and CSV
2.135 -> 2.154s. The smaller serialized payload does not materially accelerate
the complete full-history Today path.

Peak report-process RSS is 1,865,498,624 -> 1,797,488,640 bytes (-3.6%), not a
universal codec memory reduction. SQLite/WAL high-water bytes are
2,127,450,112 -> 2,072,539,136. Allowance payload peaks at
104,078,329 -> 61,717,024 bytes (-40.7%); the history reuse payload is unchanged
at 13,790,131 bytes. Post-append allowance writer ownership falls from 0.245s
to 0.170s median; first-fill ownership falls from 0.395s to 0.208s.

Every normalized complete HTML hash, CSV hash, row count and cache-hit flag
matches across all ten pairs. The only allowed HTML normalization is the issued
authorization scope documented above. CSV is byte-identical with 1,941 rows,
SHA-256 `c9645cb1f99f00ad668d1d60b41a975d4abea9dc0f9728606a3bf1f99084be79`.

Frozen identities:

- Baseline source: `e4cd5a9b13a9fbc024ce208168104d5617aa6d8424a23d745b0c163a5a0b7167`.
- Candidate source: `c305bbe185cc997fa009b7344c19e6621ef6fb2fe12f93ff9d8b1c62899333f1`.
- Benchmark harness: `a34231f2d097b7a80e017c93d871a582822d3ad8eb369e9b1135b3c4673e0106`.

## Phase Diagnostics And Remaining Work

Separate `baseline-phases` and `candidate-phases` runs use coarse function
wrappers, without cProfile. Each primes the same two ranges after revision and
opens ten distinct, issued, cold period-detail pages. These are diagnostic
samples, not additional primary adoption pairs or ten repeated identical pages.
All 12 complete HTML comparisons match under the same issued-scope rule.

| Phase | Baseline CPU | Candidate CPU |
| --- | ---: | ---: |
| Today full report encoding | 0.889s | 0.914s |
| First 30-day batch valuation | 1.026s | 0.888s |
| First 30-day turn calculations, 95 calls | 0.625s | 0.233s |
| Detail full-report decoding, median of ten distinct pages | 0.947s | 0.809s |

Detail-page wall median is 1.082 -> 0.960s; ranges are 1.045-1.101s and
0.916-1.322s. Retain the late candidate outliers. Decoding is faster in this
diagnostic despite the small synthetic allocation trade-off found by review.
Full encoding is not faster: the layout table primarily reduces payload size,
publication time and detail decoding. The scalar identity microbenchmark does
not establish full-encoder improvement.

The candidate Today diagnostic uses 7.938s CPU; encoding plus selected-event
pricing/turn work consumes about 0.928s. First 30 days uses 7.438s CPU;
pricing/turn work consumes about 1.122s and account encoding is already cached.
Even eliminating these phases entirely would leave more than 7s Today / 6s
30-day CPU in these samples. Further changes confined to these functions cannot
meet 3s/5s. The earlier whole-path profile locates remaining costs in raw/full
history preparation, source-authority/reset/economics assembly, and other range
aggregations, speed queries and chart rendering. The 30-day HTML remains about
15.85 MB; backend timing does not establish its transfer/paint cost.

The next work must address that remaining work, with ordered exact totals and
correction/causal invalidation retained. No persistent event partitions, native
runtime, reduced chart fidelity, progressive loading or reset immutability are
introduced by this pass.

## Cleanup And Delivery

The frozen input hash was rechecked unchanged before deleting that owned ledger
and its sidecars. Benchmark/profile working copies were removed; no SQLite
files remain in this pass's evidence root, now 32 MiB. Retain frozen sources,
harnesses and compact JSON evidence. The final product source still matches the
timed source manifest. No commit, push, CI, release, installation or native
activation occurred.
