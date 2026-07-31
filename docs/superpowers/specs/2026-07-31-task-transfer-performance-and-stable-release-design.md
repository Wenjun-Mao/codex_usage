# Task Transfer Performance And Stable Release Design

## Purpose

Make the extension responsive on large Codex histories, make Task Transfer list
the same user-visible tasks as Codex, and define the validation gate for removing
the Marketplace Preview label in a later `1.0.0` release.

The performance work ships first as preview version `0.1.42`. Stable promotion
is a separate release after the packaged extension has been tested on macOS
Apple Silicon and Windows x64.

## Measured Evidence

Investigation on the development Mac found:

- 2,245 active and archived session JSONL files totaling about 61 GB.
- Only 26 files represented user-visible root tasks. The other 2,219 files were
  spawned subagents, guardians, or automatic review sessions.
- `codex_usage` had 263 discovered files: one user task and 262 subagents.
- `ebook_translate` had 1,043 discovered files: one user task and 1,042
  subagents.
- Three files had appended only about 69 MB since their cached fingerprints,
  but their current combined size was about 4.1 GB. The cache reparsed all 4.1
  GB from byte zero.
- A production warm-cache report command did not finish within 108 seconds and
  was interrupted.
- Hydrating 149,281 cached usage rows, filtering seven days, and performing the
  report aggregations took about 2.2 seconds when changed-file parsing was
  removed from the measurement.
- The largest representative task was about 2.06 GB. About 99.2% of its bytes
  belonged to event types that usage accounting ignores.
- A relevance-gated prototype parsed that file in about 3 seconds.
- The prototype produced identical `UsageRecord` values to the existing parser
  across 100 representative files totaling about 887 MB.
- Scanning metadata and `session_index.jsonl` for all local files took less than
  one second.

Task Transfer currently performs two unnecessary full-content operations before
showing the picker:

1. `load_sync_session_data_read_only` parses every JSONL event stream and builds
   usage records even though transfer inventory does not consume token history.
2. `build_sync_selection_inventory` calls the full synchronization planner for
   every discovered task, which hashes local and remote files before the user
   has selected a project or task.

These two operations explain the reported multi-minute "Checking tasks" delay.

## Root Cause And Fix Layer

### What failed

The usage cache treats any size or modification-time change as a reason to
decode a complete JSONL file. Task Transfer also uses usage-oriented parsed data
and execution-oriented content snapshots for a browse-only operation.

### Why it failed

The current abstractions do not distinguish among:

- usage ingestion, which needs selected event payloads;
- transfer browsing, which needs identity and display metadata only; and
- transfer execution, which needs complete byte snapshots and hashes for the
  selected tasks only.

Task visibility is also inferred from "every valid session file," while Codex
stores user tasks and internal subagent sessions in the same session tree.

### Evidence for the diagnosis

The local project counts become identical to the Codex UI when any session with
structured `session_meta.payload.source.subagent` provenance is excluded. A
parent ID alone is insufficient because guardian and automatic review sessions
can use `source.subagent.other` without `parent_thread_id`.

The isolated timings show that metadata discovery is subsecond, while parsing
and hashing complete multi-gigabyte histories dominate picker latency.

### Why the fix belongs here

The durable fix is to define separate browse and execution contracts, not to
cache one VS Code caller or hide the delay behind different progress text. Usage
parsing should also reject irrelevant event lines before JSON decoding, because
those lines can never affect token accounting.

## Product Contract

### User-visible tasks

A task is eligible for Task Transfer when all of the following are true:

- it is in active Codex session storage;
- it has valid `session_meta` identity;
- its structured source is not a subagent source.

Any object at `session_meta.payload.source.subagent` marks the session as an
internal subagent, including:

- spawned subagents with `thread_spawn.parent_thread_id`;
- guardians or automatic reviews represented by `subagent.other`; and
- future subagent variants under the same structured key.

Subagents are omitted quietly from Import, Export, and Review. They remain fully
included in usage accounting because their tokens were consumed.

Archived sessions remain available to historical usage reports but remain
excluded from Task Transfer.

`session_index.jsonl` provides the preferred title and update timestamp. Index
membership is not required for eligibility so a valid newly imported root task
remains recoverable during index or UI lag.

### Stable release

Removing Preview means a real stable release, not only changing Marketplace
copy. Version `1.0.0` will remove the preview manifest flag and Preview/Beta
wording only after the performance and correctness fixes have shipped and been
validated on both supported platforms.

## Architecture

### Structured session classification

Session metadata parsing will expose an explicit subagent classification based
on the structured `source` value. The transfer path must not infer this from a
title, filename, model label, parent ID alone, or stringified source data.

The existing usage parser continues to preserve all session types. Filtering is
applied only while building transfer browse inventory.

### Local transfer browse inventory

Replace the usage-oriented transfer loader with a transfer-specific read-only
probe that constructs `LocalInventory` directly:

1. Enumerate active session JSONL paths.
2. Read `session_meta` and filesystem size for each path.
3. Exclude structured subagent sessions.
4. Resolve project identity from root-task metadata.
5. Merge titles and timestamps from `session_index.jsonl`.
6. Discover candidate project roots using the existing project-root logic.

The browse probe does not call `parse_session_file`, create `UsageRecord`
objects, update the usage cache, or hash complete task files.

This removes the inappropriate `CachedSessionData` dependency from Task
Transfer. The usage cache remains owned by usage commands.

### Remote transfer browse inventory

Remote browsing keeps transfer format version 3. It uses the persisted index,
path guards, file existence and size, and a streaming `session_meta` probe to
classify indexed files without hashing their complete contents.

Existing version-3 folders therefore need no migration. If an older folder
contains previously exported subagents, those entries are hidden by the same
structured source rule. No remote file is deleted or rewritten by browsing.

Unindexed or malformed remote files follow the existing conservative rule: they
are omitted with a structured inventory issue unless enough validated metadata
exists to identify them safely. Full reconstruction remains an execution or
repair concern.

### Browse inventory protocol

The selection inventory is a browse contract, not a synchronization plan. Bump
its internal protocol version and remove exact preflight `state` and `action`
from task rows. Rows contain only:

- task ID;
- title;
- updated time;
- estimated transfer bytes;
- local, remote, or both availability; and
- project identity and candidate roots at the project level.

Project and task pickers show availability rather than claiming that an
unselected task is synchronized, conflicted, or ready for a particular byte
operation.

`build_sync_selection_inventory` combines local and remote metadata directly.
It must not call `build_sync_plan` across every discovered task.

### Selected-task execution

After the user selects tasks, Import, Export, or Review performs the existing
execution preflight for only those task IDs:

1. Re-probe selected local and remote paths.
2. Validate identity and path containment.
3. Read and hash complete selected files.
4. Compare local, remote, and baseline snapshots.
5. Detect prefix relationships, conflicts, and opposite-direction changes.
6. Execute or block using the existing conservative planner.

A file changed between picker display and execution is caught here. The UI
shows a selected-task checking/progress state while this work runs.

### Usage parser relevance gate

Before calling `json.loads`, `parse_session_file` checks whether a raw line can
contain one of the event families used by token accounting:

- `session_meta`;
- `turn_context`;
- `token_count`; or
- `task_started`.

Lines without any relevant marker are skipped. Lines with a marker still pass
through the existing JSON parser and normal structural checks. A marker in user
content may cause an unnecessary parse but cannot create a usage record unless
the decoded event has the expected structure. Every relevant event necessarily
contains its marker, so the gate cannot omit a relevant event.

This change does not alter cache schema, pricing, aggregation, transition, or
token-delta semantics.

## Error Handling And Safety

- Explicit subagents are expected omissions and do not generate warnings.
- A malformed or unreadable local root candidate is omitted and reported as a
  structured inventory issue without blocking other tasks.
- Remote browse probes retain the existing path guards and never follow an
  unsafe indexed path.
- Browse inventory never writes Codex storage, the transfer folder, or the usage
  cache.
- Full selected-task preflight remains mandatory before mutation.
- Identity, size, or hash changes discovered after selection produce the
  existing conflict or issue result; they are not silently accepted.
- Parser failures remain file-scoped and do not erase previously good cached
  usage.

## Testing

### Python contract tests

- spawned subagents are excluded from transfer inventory;
- parentless `subagent.other` guardians and reviews are excluded;
- root tasks remain included;
- subagent usage remains present in usage summaries;
- archived roots remain excluded from transfer;
- a valid unindexed root remains discoverable with fallback display metadata;
- local browse inventory never calls the full usage parser or file hasher;
- browse inventory construction never calls the full synchronization planner;
- version-3 remote folders remain readable without migration;
- previously exported remote subagents are hidden;
- selected execution still hashes and validates every selected task;
- malformed metadata produces a structured issue without mutating storage; and
- filtered parsing exactly matches the existing parser for relevant fixtures.

Parser fixtures include compact JSON, whitespace-formatted JSON, irrelevant
large payloads, misleading marker text inside content, malformed JSON, forks,
model changes, collaboration modes, and token snapshots.

### VS Code tests

- browse inventory protocol parsing rejects unknown or malformed fields;
- project counts include user-visible tasks only;
- picker rows describe availability without unverified conflict claims;
- no task is selected by default;
- selecting a project still opens only that project's task list;
- execution begins selected-task checking only after task confirmation; and
- inventory issues preserve the existing concise user warning and detailed
  output-channel logging.

### Regression and packaged tests

- run the complete Python and extension suites;
- run packaged Task Transfer smoke tests on Windows x64 and macOS Apple Silicon;
- compare parser output against the existing implementation on representative
  real-data fixtures without committing private session data; and
- retain source-size guardrails when responsibilities move between modules.

## Performance Acceptance Gates

Correctness and operation-count invariants are primary; wall-clock checks are
manual because antivirus, cloud storage, and filesystem performance differ.

Required invariants:

- transfer browsing does not decode task event histories;
- transfer browsing does not hash every discovered task;
- transfer execution's complete reads and hashes scale with the number and size
  of selected tasks;
- usage parsing does not JSON-decode irrelevant events; and
- usage totals remain unchanged.

Manual targets on the measured Mac dataset:

- `codex_usage` and `ebook_translate` each show one root task;
- approximately 2,245 local files are classified in a few seconds rather than
  minutes;
- the representative 2 GB task parses in roughly 3-5 seconds;
- dashboard refresh involving the current large appended files improves
  materially from the observed 108-plus seconds; and
- selecting and preflighting one task scales with that selected task, not the
  complete 61 GB history.

Windows validation confirms that packaged startup, antivirus, and OneDrive do
not reintroduce multi-minute browse latency.

## Release Sequence

### Preview performance release: 0.1.42

- implement metadata-only browse inventory;
- exclude structured subagent sessions from Task Transfer;
- defer complete hashing and planning until after selection;
- add usage parser relevance filtering;
- update user documentation and changelogs; and
- publish both supported VSIX targets after all gates pass.

### Stable release: 1.0.0

After hands-on validation of `0.1.42` on both supported platforms:

- set extension version to `1.0.0`;
- remove `"preview": true` from the Marketplace manifest;
- replace current Preview/Beta wording in the root and extension READMEs,
  support documents, release checklist, and metadata tests;
- retain historical changelog wording for releases that were previews; and
- publish Windows x64 and macOS Apple Silicon packages through the existing
  release workflow.

Stable promotion does not bundle unrelated functional work.

## ADR Updates

Implementation adds a concise ADR defining user-visible Task Transfer sessions,
metadata-only browse inventory, and selected-task-only content validation. The
existing manual Task Transfer ADR remains the basis for explicit direction,
one-project scope, and read-only browsing.

## Rejected Alternatives

### Incremental append checkpoints now

Persisting parser offsets and complete parser state would further improve active
multi-gigabyte refreshes, but adds cache migration and recovery complexity. It
remains a follow-up if relevance filtering does not meet the acceptance gates.

### Long-running background service

A daemon could keep parsed rows and inventories in memory, but introduces
lifecycle, upgrade, crash recovery, and cross-platform process concerns that the
measured bottlenecks do not justify.

### Filter only by parent ID

This leaves parentless guardian and automatic-review subagents visible and does
not match Codex task counts.

### Require session-index membership

This matches current observed root-task counts but can hide a valid newly
imported task during registration or UI lag. Structured source classification
is the durable identity rule; the index is display metadata.

### Keep exact sync state in the picker

Exact state requires hashing every local and remote file before selection. That
turns browsing into full preflight and recreates the multi-minute delay. Exact
state belongs after the user selects tasks.
