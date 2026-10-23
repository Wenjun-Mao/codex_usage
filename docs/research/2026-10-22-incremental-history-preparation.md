# Incremental History Preparation

Date: 2026-10-22. Local source candidate only; not released or installed.

## Scope And Method

Continue the approved 3s post-capture Today / 5s first-30-day targets. This pass
adds exact-prefix display/pace reuse and exact-content chart-day reuse, not
background prewarming or reduced evidence. The contract and rejection rules are
in [ADR 0074](../adr/0074-incremental-history-preparation.md).

Use the completed second-pass candidate as baseline, not the earlier 12.66s
measurement on different data. One new coherent mode=ro backup was taken from
the live ledger; all report writes use one disposable working copy at a time.
No raw logs, account calls, live writes, private uploads, CI or normal VS Code
activation occurred. The protected rollback archive is untouched.

Private input: 881,247 usage events; 352,276 stored quota rows; 388,692 recorded
quota samples. SQLite backup: 2,071,461,888 bytes, SHA-256
`ceabe954c722d6defea1aa6b10727a3dccb340e1622d65f89747fd46c5373c09`.
Latest stored/expanded endpoint: 2026-10-22 16:03:22.998857 UTC. Fixed benchmark
clock: 16:04 UTC, America/Toronto. Python 3.13.12 / SQLite 3.50.4.

Evidence is under `output/performance/dashboard-incremental-20261022/`:

- `prototype-pair`: rejected full-scalar-fingerprinting prototype, one excluded
  preparation pair and one alternating measured pair. Exact HTML/CSV parity,
  but fingerprinting largely replaced the replay cost and slowed first fill.
- `journal-pair`: intermediate journal/display-only diagnostic. Not adoption
  evidence; later focused tests overlapped its tail. Retain its samples.
- `final-pairs`: frozen complete candidate, one excluded preparation pair and
  ten alternating unprofiled pairs. No concurrent project tests or browsers.
  External machine load is uncontrolled; retain all samples and report ranges.

The baseline includes the existing writer-admission fix and both prior
optimization passes. Do not attribute their benefits to this follow-up.

## Root Cause And Changes

Quota generation equality could reuse unchanged inputs, but any new reading
made the previous whole-series memo unusable. The fit cache deliberately reused
only monetary estimates, leaving continuity replay and day reductions fresh.

The new journal certifies a prefix only while its complete retained mutation
sequence proves that earlier inputs are unchanged. Display reuse additionally
checks resolved identities and capture membership/positions, protecting against
backward effects of later known plans and newly bracketing official evidence.
Pace reuse preserves the entire continuation cursor; it does not substitute a
summary tuple for that cursor. Unknown-plan arrival and corrections rebuild.

Chart-day certificates include the exact raw/context JSON bytes, timezone and
numeric local-day endpoints. They avoid decoding unchanged input solely to
hash it again. Monetary segmentation, reset detection, current membership,
fit ownership and ordered-prefix economics remain fresh and authoritative.

## Correctness

- First full Python run: 3,333 passed, one existing skip.
- Independent read-only review (requested Sol 6.1 / High; effective host settings
  unverified) found two guardrail gaps: writable
  rollback-generation collision, and revision-only breakdown publication.
  Both were repaired and independently rechecked; no remaining findings in
  that recheck. Reviewer reported 2,000 native-journal mutation requests and
  23,553 pace-origin comparisons; these are reviewer evidence, not manager-run
  acceptance counts.
- Post-fix full suite: 3,334 passed, one existing skip, one fixture failure.
  The receipt-only fixture needed to pass the new required source token; after
  that test-only update, all 51 focused history/journal/day/receipt checks passed.
- Ruff and diff whitespace checks pass. Exact monetary/image/repository parity
  remains `58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`.
- Bounded work: quota-only update does not reprice language events; unchanged
  speed recovery opens no sources.
- 720 synthetic browser views passed across Chromium, Firefox and WebKit,
  including script-disabled, dense history, DST, and conflict cases. A retained
  screenshot was inspected. Later fixes only tighten cache identity/publication.

Targeted tests cover prefix append/no replay, first-known plans, cross-duration
plan events, authority promotion/removal, simultaneous conflicts, earlier edits,
mixed offsets, compressed history, old writers, missing/overflowed journal,
tracking repair, writable rollback, stale publication and sparse DST neighbors.

## Measurements

Ten alternating, unprofiled pairs; one additional preparation pair excluded in
advance. All complete HTML and CSV hashes, row counts and cache-hit flags match.
The 30-day CSV has 1,937 rows and SHA-256
`49c9962ab496de1458c53d42bcfc7757f488a021291a4b6d0c1c14310e60c15a`.
Backend timings do not measure WebView transfer or paint. The first 30-day load
follows Today, so it benefits from already prepared account-wide allowance data.

| Operation | Baseline median | Candidate median | Baseline range | Candidate range |
| --- | ---: | ---: | ---: | ---: |
| First Today after revision / initial checkpoint fill | 8.785s | 9.274s | 7.758-10.450s | 8.032-15.980s |
| First 30 days | 9.986s | 10.176s | 8.404-12.538s | 8.433-14.236s |
| Cached Today | 0.078s | 0.079s | 0.073-0.411s | 0.074-0.914s |
| Cached 30 days | 0.087s | 0.088s | 0.082-0.116s | 0.083-0.094s |
| Disposable usage/quota append write | 0.075s | 0.073s | 0.069-0.460s | 0.070-0.137s |
| Today after usage/quota append | 8.791s | 8.484s | 8.080-13.207s | 7.651-14.068s |
| 30 days after usage/quota append | 8.874s | 7.525s | 8.070-14.680s | 7.290-11.919s |
| 30-day CSV | 2.486s | 2.195s | 2.219-3.160s | 2.155-2.737s |

Post-append Today improves 3.5%; post-append 30 days improves 15.2%. Neither
target is met: Today is 5.48s above 3s, and first 30 days is 5.18s above 5s.
First Today pays 0.49s more to build checkpoints; first 30 days is 0.19s slower.
No median regresses by both 10% and 100ms. Retain all machine-load outliers.
Parent CPU medians support modest gains: post-append Today 8.224 -> 7.979s,
post-append 30 days 8.444 -> 7.426s, first 30 days 8.514 -> 8.644s, and CSV
2.346 -> 2.181s. CSV code is unchanged in this pass; do not attribute the entire
wall-time difference causally to incremental history reuse.

The independent journal contained two entries after append. This append is one
usage event plus one genuinely new quota reading, not a full live capture. A
capture that updates compressed history, changes an earlier row or exceeds the
journal horizon rebuilds the affected history; no-op updates also invalidate
conservatively. The measured reuse gain is not a guarantee for every capture.

Peak report-process RSS is 1,238,466,560 -> 1,253,163,008 bytes (+1.2%). SQLite
high-water size is 2,110,001,152 -> 2,123,796,480 bytes. New serialized checkpoint
payload peaks at 13,730,369 bytes (13.1 MiB), within its 32 MiB bound. Large quota
graphs retained globally remain zero. Post-append allowance writer ownership
is 0.279 -> 0.276s median; this pass does not materially shorten that interval.

Frozen source identities:

- Baseline: `c3b3eadde3199fd502b868da998b591c681d955995850724b33c4cd8fa2e1256`.
- Candidate: `e4cd5a9b13a9fbc024ce208168104d5617aa6d8424a23d745b0c163a5a0b7167`.
- Harness: `c6a6573fcddc10cdce718a707707de87fc5527fefce4699eeee70409b2777553`.

## Remaining Work

A separate post-append cProfile run, after priming both ranges, is retained in
`reused-profile/`. Its instrumented durations are heavily inflated and are not
adoption timings; cumulative entries overlap and cannot be added as savings.

- Today: full allowance report encoding still visits 358,286 point keys;
  source-aware assembly, raw evidence loading, reset economics and monetary
  segmentation remain substantial. Incremental continuity alone cannot remove
  this full-history preparation cost.
- 30 days: 201,376 selected events are still valued, including 402,752 pricing
  schedule lookups; project/model turn metrics and chart rendering remain
  substantial. The generated HTML is about 15.75 MB. This backend profile cannot
  establish the WebView transfer/paint cost of that payload.

The next measured candidates are reducing repeated canonical report encoding
and repeated event-time pricing/turn materialization, retaining the same exact
accounting and invalidation contracts. Neither change is implemented here.
Do not infer reset immutability, skip evidence validation, retain an unbounded
object graph or weaken a test to reach a timing target.

Final cleanup confirmed the unchanged frozen input hash and deleted the owned
frozen ledger and sidecars. Benchmark/profile working copies were also removed;
no SQLite files remain in this pass's evidence root, now 24 MiB. Compact source,
JSON, profile and synthetic browser evidence are retained. This pass is locally
verified, not released, installed or natively accepted.
