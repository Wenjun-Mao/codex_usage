# ADR 0060: Historical Allowance Calculation Reuse

Status: Implemented and qualified locally. Not released.

## Context

ADR 0059 removes eager preparation of invisible chart days. The first report
after each capture still fits and serializes every historical allowance window.
A closed or old window is not immutable: recovered quota evidence, provenance,
generation replacement and late usage can change its result. A revision-only
cache therefore repeats work, but an append-only shortcut would be incorrect.

## Decision

Keep fresh segmentation, the original ordered monetary prefix, live status,
credits and capture-causal pace preparation. Reuse compact fitted results only
under transactionally recorded source invalidation. Retain the estimate, priced
coverage and fit cutoff/count, and materialize raw readings and provenance fresh.
Storing duplicate full windows made decoding expensive and did not consistently
improve loads. The cache does not retain another copy of reading history.

Optional SQLite triggers record bounded dirty spans alongside source writes.
There are at most two dirty rows, usage and quota; no growing change log. Usage
inserts, updates, deletes, generation trust changes, source-order changes and
model changes invalidate windows ending at or after the earliest affected
event. This deliberately includes changes *before* a window starts: floating
point prefix subtraction must remain exactly equivalent to the full estimator.
Updates affecting event prices remove those derived prices for recomputation.

Quota and provenance changes invalidate intersecting time spans. SQL timestamps
are enclosed by one second to cover fractional precision. Unsupported SQL
timestamps, and compressed timestamp groups whose mixed-offset interior cannot
be inspected in SQLite, conservatively invalidate all quota windows. No-op
observation upserts do not invalidate. Segmentation always runs again so
out-of-span resets, cross-bucket reset classifications and plan identity changes
still alter the cache key. Closed and ongoing windows use the same rules.

Keys bind pricing, report/algorithm revision, coverage, every segmentation field,
point count, endpoint observations and full-history versus exact causal-origin
scope. Stored bounds use all point timestamps, not lexical endpoints. Window
entries are pruned to those used by the current full and causal report, keeping
obsolete evolving windows and old contracts from accumulating.

Tracking installation, identity verification, window reuse, dirty consumption,
pruning and report publication occur in the existing guarded writer transaction.
A writer ahead of the caller's pinned snapshot falls back to that snapshot's
uncached estimator. Failure rolls back cache changes and preserves invalidation.
Missing or altered established tracking resets derived window results and event
prices. First installation retains the independently versioned valid price
index, as the previous report already did. With no prior window calculations to
reuse, installation performs all fits against that existing pricing contract.
Writable ledger connections repair existing tracking before yielding to capture
operations; this covers a partial cache reset even after a cached read. Repair
also clears complete report caches, and does not advance the source revision.
Trigger definitions are checked exactly, including case-sensitive SQL literals.
Old collectors using the same tables still fire these SQLite triggers.

Complete account reports also store each window once, with index references for
history, qualified windows and the headline. The decoder restores the complete
original report shape, order, values and shared ownership. The versioned codec
can decode prior bare JSON, and new storage has a distinct `cache-format` suffix
in the full-report and compact pace-state keys. Older readers therefore never
receive a new wrapped payload under their old key. The event-price identity and
monetary report semantics stay unchanged; a storage format revision cannot force
event repricing. The fitted-window cache also binds the report's storage identity.

Capture-causal pace references materialize only fitted window summaries. Their
consumer selects estimates and timing/identity metadata and never reads raw
reading dictionaries. Full report windows continue to materialize every original
reading and provenance label. The fixed quota metadata exporter uses direct
field access; a dataclass-parity test guards the complete allowlisted schema.
Profiling identified over 600,000 dictionary exports per revision-only reload,
including the unused causal reading projection.

## Alternatives And Tradeoffs

A first experiment hashed every expanded observation, its provenance and its
relative cost prefix. Exact report parity passed, but hashing and decoding cost
more than the saved work. A second stored full fitted windows, which removed
fits but duplicated reading serialization/decoding. Both were replaced by the
compact fitted-result format before qualification. Frozen-ledger inspection
then found a 95 MB complete report with 172,000 duplicate historical reading
entries; reference storage avoids that duplicate serialization and disk payload.

Rejected keeping old report JSON wholesale, inferring immutability from age or
latest timestamp, hashing raw blobs without considering provenance, and changing
cost arithmetic to simplify invalidation. Once tracking is established, reusing
prices after tracking is lost would hide a possible stale-price interval.

The new tracking adds small writes to capture transactions and one-time setup
work. Compressed recovery, early usage corrections, pricing changes or damaged
tracking may require broad recomputation. Raw quota loading, continuity/pace
preparation, segmentation, prefix accumulation and final HTML rendering are
still history-dependent. This is not constant-time or instant cold navigation.

## Verification

`tests/test_allowance_window_cache.py` compares complete reports against the
uncached estimator after append, late insert/update/delete, generation trust,
source ordering, model changes, quota conflict/correction, provenance, compressed
mixed-offset evidence, future plan resolution, full-meter conflicts, pricing,
coverage, missing/altered tracking, transaction rollback and concurrent capture.
It asserts zero historical fits on a revision-only change, historical reuse on
append, bounded compact cache retention, fresh account status independently of
reuse, first-install price preservation, and reset -> cached read -> capture
recovery.
`test_allowance_report_codec.py` verifies exact round trips, reference ownership,
legacy decoding, empty summaries, size reduction and rejection of invalid or
foreign window references. Format-key tests preserve priced events across a
storage revision.
Reference projection tests forbid raw dictionary exports and compare every
summary and selected reference against full windows with identical fitted values.

`scripts/benchmark_allowance_reuse.py` alternates baseline and candidate processes
on copies of a frozen read-only ledger. It compares full HTML hashes at a fixed
clock through first fill, revision-only, current append, late usage and late quota
changes. It records wall/CPU load times, synthetic mutation time and actual window
fit counts. The shared benchmark-only breakdown presentation revision permits
full HTML comparison; monetary pricing/report identities are not overridden.
No live capture, quota RPC, task-body read, native painting, install or release is
performed. First setup and ordinary subsequent post-capture loads are reported
separately; local timings are workload evidence, not a universal latency promise.

## Measured Results And Remaining Work

Three alternating runs against the ADR 0059 source checkpoint on the same frozen
ledger produced these medians. Every paired full-HTML hash matched, including
late usage and late quota corrections. These compare this change against the
preceding local implementation, not the installed 2.12.1 extension.

| Operation | Before | After | Window fits before / after |
| --- | ---: | ---: | ---: |
| First setup | 4.97 s | 4.99 s | 530 / 530 |
| Revision-only reload | 4.69 s | 4.34 s | 530 / 0 |
| Appended usage and quota | 4.59 s | 4.32 s | 265 / 1 |
| Late historical usage | 4.72 s | 4.08 s | 265 / 265 |
| Late historical quota | 4.53 s | 4.21 s | 265 / 265 |

Revision-only CPU decreased from 4.63 to 4.25 seconds, and append CPU from 4.48
to 4.22 seconds. The complete report cache shrank from 95.23 MB to 48.46 MB
(decimal units), without dropping readings. A synthetic transaction inserting
10,000 events increased from 0.043 to 0.213 seconds: roughly 17 microseconds of
additional tracking work per event in this benchmark. This measures source
inserts, not total capture/network/parse latency. Ordinary captures with far
fewer new events do not inherit the whole batch's added time.

`pytest -q`: 1,884 passed, one expected skip. Changed-file Ruff and
`git diff --check` passed. An earlier suite hit the unchanged two-second fake RPC
startup deadline; its isolated 14-test rerun and subsequent complete suites
passed without altering timeouts. Independent read-only review found and helped
close the partial-reset capture failure, then found no additional invalidation,
transaction or codec defects. The reviewer was collected and closed.

This establishes correct historical fit reuse and a modest measured reduction,
not a complete solution to loading latency. Raw evidence loading, full-history
continuity/pace preparation, fresh segmentation, exact-reading presentation and
prefix accumulation remain recurring work. First setup still performs all fits;
late historical corrections may correctly require all fits again. Multi-process
writer contention and real native VS Code capture/painting are not qualified by
these backend benchmarks. No live ledger, installed extension, version, release
or unrelated `apps/` files were changed.
