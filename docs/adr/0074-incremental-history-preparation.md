# ADR 0074: Incremental History Preparation

Date: 2026-10-22. Status: locally implemented and verified; unreleased.

## Problem

ADR 0073 removed duplicate work and shortened writer admission, but quota
changes still replay old display and pace continuity. Revision-scoped chart
days also repeat reduction after capture. The previous paired medians were
8.86s for Today after append and 10.35s for first 30 days, above 3s/5s targets.

An initial exact-prefix prototype hashed every raw scalar. It preserved output
but its hashing cost erased the replay saving. That version is not adopted.

## Decision

Extend the independently owned dashboard tracking contract with a bounded
4,096-entry quota mutation journal. Quota/provenance triggers record the new
quota generation and a conservative earliest affected time. Updates include old
and new values; provenance changes resolve their observation. Missing metadata,
unparseable timestamps and compressed timestamp blobs invalidate all history.
Both uncompressed endpoints participate, including mixed offsets. SQL second
precision is widened by one second. Journal gaps, overflow, epoch changes or
rollback cannot certify an unchanged prefix. Repair installs a fresh epoch.
This journal never consumes the monetary fit cache's dirty spans.

Store disposable preparation in its own versioned, checksummed SQLite table,
bounded to 32 MiB of serialized payload and 8 MiB per entry. Evict least-recently
used entries deterministically. Do not retain large Python history graphs
between requests. Reuse/publication is eligible only for a connection opened in
mode=ro and already in a read transaction; writable generation rollback cannot
publish pending results after a generation-number collision. Read from that
pinned snapshot and stage serialization outside
writer ownership. Publish only with matching ledger revision and independent
source token. The breakdown publisher applies that guard to its entire payload,
not only the checkpoint rows. A race serves the pinned result without publishing
stale state.

Three components may reuse work:

1. Display-authority lanes, separately per limit: retain complete active
   continuity, fragment membership, plan and taint state. Resume only when the
   journal proves the previous raw prefix unchanged and a fresh fingerprint of
   resolved limit-wide identities, timestamp groups and canonical positions
   matches. Later known plans or moved task membership can invalidate this
   fingerprint even when their raw observations occur after the checkpoint.
   Rebuild a mismatching lane; do not attempt suffix convergence.
2. Pace series: retain the complete Cursor/Continuity and dictionary-packed
   per-origin checkpoints and cycle statistics. Rebuild groups and all-duration
   plan events from current evidence. Resume only with the unchanged-prefix
   certificate and unchanged first-known-plan position. Earlier causal origins
   remain unchanged. Same-time additions and first-known-plan arrival rebuild.
3. Chart-day reduction: identify the exact serialized raw day and actual
   per-series cross-day neighbors, plus timezone, day, kind and algorithm
   version and numeric local-day endpoints. Read their existing serialized payloads before decoding. An
   unchanged day can reuse its reduced output across capture revisions. Sparse
   neighbors need not be adjacent calendar days.

Recompute task corroboration/authority, current flags, fit ownership, monetary
segmentation, reset-period detection and economics from the current snapshot.
Keep the original ordered monetary prefix, all raw readings and exact visible
output. Closed periods are not presumed immutable. No prices, sample populations,
calendar boundaries, fidelity, or UI text change.

## Consequences And Verification

First fill pays checkpoint construction/serialization; subsequent appends may
reuse it. This is not capture prewarming. The journal adds bounded transactional
work to capture, which must be measured. SQLite file/WAL high-water sizes may
exceed the serialized cache budget because of page allocation and free pages.

Tests compare fresh and incremental results across changed plans, uncertain
task promotion, same-time conflicts, earlier insertions/deletions/corrections,
mixed offsets, compressed timestamps, all-duration plan changes, legacy writers,
tracking repair, journal gaps/overflow, rollback, stale publication and DST.
Full HTML/CSV equality and matched unprofiled timings govern adoption; faster
replay alone is not proof of a faster dashboard. Existing browser and monetary
verification remains required. Local checks do not authorize CI or release.

Ten matched pairs measured post-append Today 8.79 -> 8.48s and post-append
30 days 8.87 -> 7.52s. First fill is slower: Today 8.79 -> 9.27s and first
30 days 9.99 -> 10.18s. Serialized reuse payload peaks at 13.1 MiB. The 3s/5s
targets remain unmet; full report encoding and selected-event economics still
dominate. See [local evidence](../research/2026-10-22-incremental-history-preparation.md)
for exact parity, review findings/fixes, timing ranges and limitations.
