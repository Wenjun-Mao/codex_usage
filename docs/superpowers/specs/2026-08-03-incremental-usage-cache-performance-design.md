# Incremental Usage Cache Performance Design

**Date:** 2026-08-03  
**Status:** Approved for implementation planning

## Context

The persistent SQLite cache introduced in the 2026-05-25 design stores parsed
usage records, but a report command still performs work that is proportional
to the complete Codex history.

A live packaged-1.0.0 audit on the development Mac measured:

- 2,407 current session files totaling 88.39 GiB;
- a 99 MiB plugin cache containing 163,340 usage rows;
- three changed session files totaling 3.61 GiB on one report refresh; and
- a project-transition scan of all 2,407 session files after those three files
  invalidated transition inference.

The cache does reuse unchanged usage generations. The repeated source I/O
comes from a broader invalidation contract: any successful file refresh marks
all project transitions dirty, and dirty transitions reopen every JSONL file.
After that work, the query path materializes every cached usage row and applies
the requested date range in Python. Parallel workers reduce wall-clock time but
do not reduce bytes read.

## Goals

- Preserve exact-refresh behavior without a TTL or deliberately stale report
  reuse.
- Never open an unchanged JSONL file during a warm report refresh.
- Read each changed JSONL file once while producing both usage records and
  project-transition candidates.
- Recompute project transitions only for tasks affected by changed, new, or
  removed files.
- Query only usage rows needed by the selected report range, plus the minimum
  context required for identity and transition correctness.
- Prevent rapid setting changes from creating concurrent report processes.
- Show a simple end-to-end `Loaded in X.X seconds` value in the dashboard.
- Emit phase timings to the extension Output channel for future diagnosis.
- Retain complete-file generation recovery and parent-only SQLite ownership.

## Non-Goals

- Append-offset or partial-file checkpoints.
- Caching rendered HTML reports.
- A daemon, long-running Python service, or Node-side session parser.
- Cancelling a running Python process and its worker tree.
- Preserving or migrating schema-3 cache contents.
- Changing pricing, aggregation, task-transfer, or public CLI semantics.

## Freshness Contract

Every displayed refresh performs a current source inventory. Changed or new
files are parsed before the report query runs. There is no time-based reuse
window.

A completed report reflects the latest complete file generations successfully
observed by that refresh. If a source file grows after its inventory
fingerprint is captured, the next refresh sees the mismatch and refreshes that
file again. This retains the existing conservative behavior for active Codex
tasks without promising an impossible atomic snapshot across independently
appended files.

When settings change during a running refresh, the extension eventually
renders the newest requested settings. It does not render an obsolete result
as if it belonged to the newest request.

## Disposable Schema 4 Cache

The cache is derived data, not user-owned data. Schema 4 is therefore the only
supported format after this change.

When the CLI encounters an older or incompatible schema, it deletes and
recreates the plugin cache. It does not snapshot old rows, backfill them, carry
legacy project transitions, or maintain dual read paths. Codex source JSONL
files and `state_5.sqlite` remain untouched.

The first report after upgrading performs one intentional cold rebuild. The
loading view says `Rebuilding usage cache after upgrade...`, and the completed
dashboard reports the elapsed time. The combined parser reads each source
JSONL once during this rebuild rather than running a second transition pass.

Schema 4 retains the existing cache tables and adds:

- `usage_records.timestamp_us`, an integer UTC timestamp used for range and
  session queries;
- `transition_candidates`, containing complete raw candidate generations keyed
  by file key and candidate order; and
- indexes for `usage_records(timestamp_us)`,
  `usage_records(session_id, timestamp_us)`, and transition-candidate task/file
  lookup.

The original timestamp text remains available for diagnostics and stable
serialization. Range comparisons use `timestamp_us`, avoiding lexical
comparison problems between timestamps with different UTC offsets.

## Combined Changed-File Parsing

The file worker reads one JSONL stream and sends each relevant decoded event to
two collectors:

1. the existing usage-record state machine; and
2. the raw project-path candidate collector.

The worker returns one result containing a complete usage generation, a
complete raw-candidate generation, the parsed session metadata needed for the
file summary, its source fingerprint, and timing data. Parent-side cache writes
must use that returned metadata rather than reopening the JSONL through the
current metadata fallback. The worker does not access SQLite or verify mutable
repository paths.

The parent process verifies raw candidates with one refresh-wide verification
cache. In one transaction it replaces the successful file's usage rows,
session metadata, candidate rows, and fingerprint. A parse, transport, or
verification failure preserves the previous complete generation for all of
those records and records the error. Partial generations are never visible.

Removing a file removes its candidate generation and identifies affected task
IDs before applying the existing missing-file retention policy to usage data.

## Incremental Project Transitions

Transition inference is independent by task ID in the existing algorithm.
Schema 4 makes that ownership explicit.

For each refresh, the affected task set is the union of task IDs found in the
old and new usage records, old and new transition candidates, removed-file
metadata, and relevant Codex state observations for changed files. The parent
then:

1. loads all cached usage records for only those task IDs;
2. loads cached transition candidates for only those task IDs;
3. reads the small Codex state database once when transition work is required;
4. verifies and infers transitions for the affected task set;
5. deletes prior transition rows owned by those task IDs; and
6. inserts the replacement rows in the same parent-owned transaction boundary.

Transitions for unaffected tasks remain unchanged. A cold schema-4 rebuild
marks every discovered task as affected, so its result must match the existing
global transition oracle exactly. A warm refresh never reopens an unchanged
JSONL merely to rebuild transitions.

State-database observations retain the existing trigger semantics: they are
consulted when changed session files require transition work. This design does
not add polling or state-only transition invalidation that the current product
does not provide.

## Range-Aware Cache Queries

The CLI computes local report boundaries with the existing timezone rules,
converts them to UTC microseconds, and passes those bounds into the cache load.
SQLite selects only rows satisfying the range. The `all` range intentionally
continues to load all rows.

Range-selected rows can depend on a parent task identity outside the selected
range. After the first query, the loader collects referenced parent task IDs
and performs an indexed lookup for one authoritative identity record per
parent. It then applies the existing parent-identity inheritance logic without
materializing unrelated usage rows.

Known project transitions are loaded from their small table and applied to the
selected records. Project filters, pricing, aggregation, and rendering remain
outside the cache because their settings and effective-dated rates can change
independently of parsed source generations.

## Refresh Coordination

The VS Code extension owns one report-refresh coordinator.

- At most one report process runs at a time.
- A request arriving during a running refresh replaces one pending request
  with the newest settings snapshot.
- The running process is allowed to finish so its worker tree and SQLite
  transaction are not interrupted.
- An obsolete result is discarded rather than rendered.
- When the running process exits, the coordinator starts exactly one pending
  refresh using the newest settings.
- Errors belong to the settings snapshot that produced them and cannot replace
  a newer successful dashboard.

This bounds expensive process concurrency at one while preserving exact
refresh behavior for the final selection.

## Visible And Diagnostic Timing

The extension measures from the beginning of refresh preparation through
successful report-file reading. The rendered control row displays
`Loaded in X.X seconds` for the report currently shown. Obsolete and failed
requests do not update this value.

The extension also passes a suppressed internal timing-output path to the CLI.
The CLI atomically writes a versioned JSON sidecar containing at least:

- inventory;
- usage refresh;
- transition refresh;
- range query;
- aggregation and rendering; and
- total CLI elapsed time.

The extension writes these phases and its own end-to-end elapsed time to the
Codex Usage Output channel. Failure to write, read, or parse the optional
timing sidecar is logged but never fails an otherwise valid report.

## Error And Recovery Behavior

- Cache-schema mismatch resets only the plugin cache.
- Cache creation and file-generation replacement remain transactional.
- Failed changed-file work preserves the previous complete generation and
  reports the file error.
- Infrastructure failure retains the existing observable serial fallback.
- Range-query failure follows the existing cache-unavailable error path; it
  does not silently label a direct full parse as a cache hit.
- Refresh coordination uses `finally` cleanup so one failed request cannot
  leave the coordinator permanently busy.
- Timing instrumentation is observational and cannot alter report results.

## Testing And Acceptance

### Cache And Parser Tests

- Schema 3 is reset rather than migrated, and source data remains untouched.
- A cold schema-4 build reads every discovered JSONL exactly once.
- A warm refresh with no changes opens no JSONL files.
- One changed file is opened once and replaces usage and candidate generations
  atomically.
- Failed parsing or verification preserves both prior generations.
- Removed files update only their affected task transitions.
- Spawned workers cannot open SQLite.

### Semantic Equivalence Tests

- Cold and incremental transition results match the current global oracle.
- Range-aware results match the current full-load-then-filter oracle for
  `today`, `yesterday`, `7d`, `30d`, `month`, and `all`.
- Tests cover non-UTC timezones, DST boundaries, parent identity inheritance,
  project transitions, forks, subagents, retained missing files, and project
  filters.
- Pricing, credit, and generated HTML payloads remain semantically identical
  for a fixed generation time.

### Extension Tests

- Rapid settings changes never exceed one report process.
- Multiple pending changes collapse to the newest settings.
- Obsolete success and failure results cannot overwrite the newest report.
- The visible timer belongs to the displayed request and is formatted
  consistently.
- Timing-sidecar errors are logged without replacing a valid report.

### Packaged Acceptance

The macOS Apple Silicon and Windows x64 package gates prove:

- a cold build uses actual bounded parallel workers;
- a warm unchanged report has zero source-file parse spans;
- a one-file change has one combined parse span and no unchanged transition
  scans;
- range-query output matches the full-load oracle; and
- packaged refresh coordination and registration smokes still pass.

The live development corpus should be measured before and after implementation.
Acceptance is structural rather than tied to one machine's seconds: unchanged
source bytes read must be zero on a warm refresh, and changed-source bytes read
must be bounded to the changed files rather than the 88.39 GiB corpus.

## Documentation And Release

Add a new ADR documenting disposable cache schemas, combined per-file parsing,
per-task transition ownership, range-aware cache queries, and latest-request
refresh coordination. ADR 0019's complete-generation and parent-only SQLite
contracts remain in force.

Update the README and both changelogs with the visible load timer and
incremental-cache behavior. The release is `1.1.0`: public report and command
contracts remain compatible even though the unsupported internal cache format
is intentionally reset.

## Rejected Alternatives

### Rendered HTML Cache

An HTML cache is fast only while source generations remain unchanged. Active
Codex tasks would invalidate it continuously under the exact-refresh contract,
and range/project/theme keys would duplicate existing reporting state.

### Append Checkpoints

Byte offsets could avoid rereading a changed multi-gigabyte active file, but
they require truncation detection, partial-line recovery, atomic offset and
record commits, and a new interruption contract. Measure schema 4 before
reconsidering this separately.

### Cancelling Obsolete Processes

Cross-platform cancellation must safely terminate spawned workers and avoid
interrupting SQLite transactions. Latest-request serialization captures the
important concurrency win without adding that process-tree risk.

### Schema-3 Migration

The cache contains only reproducible derived data. Preserving old rows would
require backfill, legacy transition ownership, and dual-schema tests while
still leaving incomplete candidate history. A single cold rebuild is simpler
and establishes one coherent schema-4 generation.
