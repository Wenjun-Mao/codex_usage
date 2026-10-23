# ADR 0073: Snapshot-Pinned Dashboard Preparation

Date: 2026-10-22. Status: implemented and correctness-verified locally;
performance targets unmet. Not released.

## Problem And Evidence

Long-range rendering repeatedly constructs immutable accounting totals and
export-only agent structures. Account preparation repeatedly hashes/parses quota
observations, reconstructs their exported dictionaries, and decodes complete
history to render the initial history directory. The allowance index also owns
writer admission throughout expensive pure computation. ADR 0072 prevents the
same-process writer race but does not eliminate that wait.

The frozen October 22 input contains 879,412 usage events and 350,355 stored quota
rows. Its matched source baseline takes about 20 seconds for the first 30-day
view. Profiles identify aggregation, history preparation and record construction
as substantial costs; instrumented times are not adoption measurements.

## Decision

Preserve one pinned, consistent report snapshot and the existing visible output.
Use request-local mutable accumulators, freezing results at their existing
boundaries. Add each record in the original consumer's order, including floating
components. Do not replace ordered accumulation with SQL SUM or daily totals.
The dashboard builds daily agent summaries only; explicit CSV and the structured
materialization API retain the complete agent export path. Account-wide speed
uses normalized timestamp/task/model facts without constructing unused ownership
records; project-filtered speed retains transition resolution.

Create one request-local canonical capture directory. Shared immutable quota
observations memoize only derived hash/time scalars, which never enter evidence
serialization. Reuse a single immutable raw/pace preparation across requests only
for pinned mode=ro connections with the same canonical path, file identity,
tracking epoch and quota generation. Retain at most 50,000 expanded points and
one ledger's preparation. Larger inputs use request-local preparation. Mutable
capture dictionaries, reports, connections and writable transactions are never
cached. A usage-only revision may reuse quota evidence; any quota observation or
provenance change rebuilds the raw quota component. The first two passes did
not reuse continuity across captures. The bounded follow-up is defined in
[ADR 0074](0074-incremental-history-preparation.md); reset and monetary
segmentation remain fresh, not implicitly assumed safe.

The second pass reduced the original 500,000-point limit after a matched
retention-eviction experiment showed that the 387,000-point raw/pace graph slowed
unrelated CSV exports. This is an optional memo budget, not an evidence cap:
larger histories are fully prepared within the request and remain available in
the existing persisted report/fit caches. No global GC settings are changed.

Within each request, share immutable provenance sets, scalar identity schemas
and repeated pace checkpoints. Index pace inputs once, keeping plan events from
every duration, and reuse the primary reset-series membership index. Chart
boundary detection retains exactly the original observations and conflicts;
it does not compute unused extrema merely to identify boundaries. None of these
representations extends cross-capture boundary authority.

Stream the selected SQL rows into the existing records instead of retaining a
second full row list. Reuse context metadata by normalized context ID and Paths
by exact source path only within that SQL query. The query owns these maps;
later queries, corrections and rollbacks always read fresh metadata. Record
order, timestamp parsing, role validation, tokens and event pricing are unchanged.

An independently owned SQLite trigger namespace tracks source and quota
generations. Native triggers also fire for compatible older writers. Missing or
damaged tracking gets a new epoch; it cannot certify cached preparation. These
counters never consume the fitted-window cache's dirty spans. No canonical
ledger/parser format, writer capability or raw source changes are required.

Read prices/fits and compute report, history projection and encoded payloads
outside writer admission against the pinned snapshot. Stage missing prices and
fits. In a short admitted write transaction, require the original ledger
revision and independent source token to match before publishing all derived
rows and consuming owned fit dirtiness. A mismatch returns the consistent pinned
report without publishing staged caches or retrying. Existing report-scope
expiry rules still govern navigation after concurrent capture.

The optional `:history-overview-1` row contains the history directory and endpoint
captures. It shares the full report's revision/pricing/coverage key and atomic
publication. Default history navigation reads it; explicit capture/fit inspection
uses the unchanged complete codec. Invalid/missing projections fall back to the
full authoritative cache. Reset and diagnostic histories own distinct capture
indices and must not exchange endpoint dictionaries.

## Consequences And Guardrails

The writer owns publication rather than segmentation/encoding. Long read
snapshots can still retain WAL pages; record WAL/database growth and publication
duration. Cold fills stage all missing price tuples in memory. Measure their
peak separately; if material growth appears on larger inputs, spool staged
publication data privately without moving pricing back into writer ownership.
No background service, prewarming, progressive rendering, stale values or second
selected-event store is introduced.

Oracle checks compare exact monetary components, all HTML bytes, CSV rows, turn
populations and history references. Regression coverage includes DST, ancestry
cycles/missing parents, numeric identity, corrupted overview fallback, old-writer
changes, tracking repair, writable rollback, and capture committing during pure
preparation with stale publication rejected even without a revision bump.

Bounded work, browser checks and timing use the existing verification tools.
The baseline includes ADR 0072's writer fix, so its benefit is not attributed to
this optimization. Local qualification does not authorize CI, release, installed
extension changes or native VS Code activation. See the
[implementation plan](../plans/dashboard-preparation-performance.md) for targets,
measurement boundaries and remaining work.
