# Incremental Usage Cache Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make exact-refresh usage reports read only changed Codex session files and the requested SQLite time range, while displaying end-to-end load time and preventing overlapping report processes.

**Architecture:** Replace the disposable schema-3 cache with schema 4, whose complete per-file generations contain usage deltas, parsed metadata, and raw transition candidates produced by one worker pass. Parent-owned SQLite code incrementally replaces affected task transitions and serves range-bounded records; a latest-request VS Code coordinator serializes report processes and publishes only the newest result.

**Tech Stack:** Python 3.12+, SQLite, `pytest`, multiprocessing with `spawn`, Pydantic settings, TypeScript, VS Code extension APIs, Node test runner, PyInstaller, VSCE, GitHub Actions.

## Global Constraints

- Preserve exact-refresh behavior: no TTL, rendered-report cache, daemon, or deliberately stale result.
- Cache schema 4 is disposable; schema 3 is reset and never migrated.
- Never modify Codex JSONL files or `state_5.sqlite`.
- Read each changed JSONL exactly once and never open an unchanged JSONL during a warm refresh.
- Keep complete-file generations, parent-only SQLite ownership, eight-file commit groups, bounded `spawn` workers, and observable infrastructure fallback from ADR 0019.
- Do not add append offsets, partial generations, process cancellation, or state-only transition polling.
- Preserve pricing, aggregation, task-transfer, and public CLI result semantics.
- Keep new and modified Python modules below 500 lines and split responsibilities before crossing that limit.
- Use `tenacity` for retryable file operations already covered by the parser/cache retry contract.
- Use `apply_patch` for manual edits and `uv` for Python commands.
- Target macOS Apple Silicon and Windows x64 packaged extensions.
- Prepare a backward-compatible public `1.1.0` release; only the unsupported internal cache format resets.

---

## File Structure

### New Python Modules

- `src/codex_usage/session_generation_models.py`: immutable combined-generation and transition-candidate value types.
- `src/codex_usage/session_cache_generations.py`: atomic usage, metadata, candidate, and file-row generation storage.
- `src/codex_usage/session_cache_queries.py`: indexed range, task, parent-identity, candidate, and transition queries.
- `src/codex_usage/session_cache_transitions.py`: dirty-task ownership and incremental transition replacement.
- `src/codex_usage/usage_context.py`: range-aware CLI context loading, keeping `cli.py` below the size limit.
- `src/codex_usage/performance_timing.py`: monotonic phase recording and atomic timing-sidecar output.

### New Extension Module

- `extensions/vscode/src/latestRefreshCoordinator.ts`: pure latest-request serialization and publish gating.

### New Focused Tests

- `tests/test_session_generation.py`
- `tests/test_session_cache_schema_v4.py`
- `tests/test_session_cache_generations.py`
- `tests/test_incremental_transitions.py`
- `tests/test_range_cache_queries.py`
- `tests/test_performance_timing.py`
- `extensions/vscode/test/latestRefreshCoordinator.test.js`

Existing tests remain oracle and regression coverage. Move old schema-rebuild tests out of `tests/test_session_cache.py` or delete them when their compatibility contract is intentionally removed; do not leave tests asserting schema-3 row preservation.

---

### Task 1: Disposable Schema 4 And Indexed Storage Contract

**Files:**
- Create: `tests/test_session_cache_schema_v4.py`
- Modify: `src/codex_usage/session_cache_schema.py`
- Modify: `src/codex_usage/session_cache.py`
- Modify: `src/codex_usage/session_cache_models.py`
- Modify: `tests/parallel_cache_test_support.py`
- Modify: `tests/test_session_cache.py`
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

**Interfaces:**
- Produces: `CACHE_SCHEMA_VERSION = 4`.
- Produces: `CACHE_DB_NAME = "usage-cache-v4.sqlite3"` and `LEGACY_CACHE_DB_NAMES = ("usage-cache.sqlite3",)`.
- Produces: `CacheSchemaState(created: bool, reset: bool, reset_reason: str)` from `_ensure_schema(connection)`.
- Extends: `CacheStats.legacy_cleanup_errors: int = 0`.
- Produces: `legacyCacheDbPath(globalStoragePath: string): string` for loading-copy detection.
- Schema provides `usage_records.timestamp_us`, `transition_candidates`, `dirty_transition_tasks`, `project_transitions.owner_thread_id`, and required indexes.

- [ ] **Step 1: Write failing schema-reset and shape tests**

```python
def test_schema_three_is_discarded_instead_of_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    create_schema_three_database(db_path, sentinel_total_tokens=999)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    assert state.reset_reason == "schema 3"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from usage_records").fetchone()[0] == 0
        assert connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()[0] == "4"


def test_schema_four_contains_incremental_query_contract(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        objects = normalized_sqlite_master(connection)

    names = {(kind, name) for kind, name, _table, _sql in objects}
    assert ("table", "transition_candidates") in names
    assert ("table", "dirty_transition_tasks") in names
    assert ("index", "usage_records_timestamp_us_idx") in names
    assert ("index", "usage_records_session_timestamp_idx") in names
    assert ("index", "transition_candidates_thread_idx") in names
```

Add a TypeScript assertion that the new cache path is `cache/usage-cache-v4.sqlite3` and the legacy path remains detectable as `cache/usage-cache.sqlite3`.

- [ ] **Step 2: Run focused tests and confirm the old contract fails**

Run:

```bash
uv run pytest tests/test_session_cache_schema_v4.py tests/test_session_cache.py -q
cd extensions/vscode && npm test -- --test-name-pattern="cache"
```

Expected: Python fails because schema 3 is still snapshotted/restored and schema-4 objects do not exist; Node fails because the cache path still names the legacy database.

- [ ] **Step 3: Replace snapshot migration with destructive schema creation**

Implement these exact value types and constants:

```python
@dataclass(frozen=True, slots=True)
class CacheSchemaState:
    created: bool = False
    reset: bool = False
    reset_reason: str = ""


CACHE_SCHEMA_VERSION = 4
PARSER_CACHE_VERSION = 3
PROJECT_TRANSITION_CACHE_VERSION = 2
```

`_ensure_schema` must:

1. return an empty `CacheSchemaState` when all three versions match;
2. begin one immediate transaction when they do not;
3. record the prior schema version for `reset_reason`;
4. drop only known plugin-cache tables and indexes;
5. create schema 4 and metadata;
6. commit and return `CacheSchemaState(created=not prior_tables, reset=bool(prior_tables), reset_reason=f"schema {prior_version}" if prior_version else "unrecognized schema")`; and
7. roll back on any exception.

Delete `CachedRowsSnapshot`, `_snapshot_cached_rows`, `_restore_cached_rows`, and their compatibility-only tests. Do not retain a dual-schema branch.

Create schema 4 with the existing columns plus:

```sql
timestamp_us integer not null
```

on `usage_records`, and:

```sql
create table transition_candidates (
    file_key text not null,
    candidate_index integer not null,
    timestamp text not null,
    timestamp_us integer not null,
    thread_id text not null,
    raw_path text not null,
    source text not null,
    primary key (file_key, candidate_index)
)
```

```sql
create table dirty_transition_tasks (
    thread_id text primary key
)
```

Add `owner_thread_id text not null` to `project_transitions`. Create the indexes named by the tests.

- [ ] **Step 4: Adopt the versioned filename and legacy cleanup contract**

In `session_cache.py`, use:

```python
CACHE_DB_NAME = "usage-cache-v4.sqlite3"
LEGACY_CACHE_DB_NAMES = ("usage-cache.sqlite3",)
```

After schema 4 opens successfully, remove legacy database, `-wal`, and `-shm` files with a focused retry helper that ignores `FileNotFoundError` and retries other `OSError` failures three times with exponential backoff. Never remove the new database on cleanup failure; increment `CacheStats.legacy_cleanup_errors` once per path that still fails after retries.

In `core.ts`, return the versioned path from `cacheDbPath` and add `legacyCacheDbPath`.

- [ ] **Step 5: Update exact schema fixtures and pass focused tests**

Update `EXPECTED_SCHEMA_META` and `EXPECTED_SQLITE_MASTER` in `tests/parallel_cache_test_support.py` to enumerate every schema-4 table and index. Remove schema-3 restore assertions from `tests/test_session_cache.py`; retain corruption rollback, parse retry, archived/missing, and cache-dir tests.

Run:

```bash
uv run pytest tests/test_session_cache_schema_v4.py tests/test_session_cache.py tests/test_parallel_cache_equivalence.py tests/test_python_source_size.py -q
cd extensions/vscode && npm test -- --test-name-pattern="cache"
```

Expected: PASS.

- [ ] **Step 6: Commit schema 4**

```bash
git add src/codex_usage/session_cache_schema.py src/codex_usage/session_cache.py src/codex_usage/session_cache_models.py tests/test_session_cache_schema_v4.py tests/test_session_cache.py tests/parallel_cache_test_support.py extensions/vscode/src/core.ts extensions/vscode/test/core.test.js
git commit -m "refactor: reset usage cache on schema 4"
```

---

### Task 2: One-Pass Session Generation Parser

**Files:**
- Create: `src/codex_usage/session_generation_models.py`
- Create: `tests/test_session_generation.py`
- Modify: `src/codex_usage/parser.py`
- Modify: `src/codex_usage/project_transition_candidates.py`
- Modify: `src/codex_usage/parallel/usage.py`
- Modify: `tests/test_parser_aggregation.py`
- Modify: `tests/test_parser_relevance_gate.py`
- Modify: `tests/test_project_transition_evidence.py`
- Modify: `tests/test_spawn_sqlite_isolation.py`

**Interfaces:**
- Produces: `RawRepoPathCandidate` in `session_generation_models.py`.
- Produces: `ParsedSessionGeneration(records, metadata, candidates)`.
- Produces: `parse_session_generation(path: Path) -> ParsedSessionGeneration`.
- Preserves: `parse_session_file(path) -> list[UsageRecord]` and `collect_jsonl_repo_path_candidates(path) -> list[RawRepoPathCandidate]` as wrappers over the shared scanner.
- Changes: `UsageParseResult` carries `generation: ParsedSessionGeneration | None` rather than records alone.

- [ ] **Step 1: Write failing one-open and semantic tests**

```python
def test_combined_generation_opens_jsonl_once_and_returns_all_products(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = write_session_with_usage_and_workdir(tmp_path)
    original_open = Path.open
    opens = 0

    def counted_open(path: Path, *args: object, **kwargs: object):
        nonlocal opens
        if path == session:
            opens += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    generation = parse_session_generation(session)

    assert opens == 1
    assert [record.usage.total_tokens for record in generation.records] == [100, 50]
    assert generation.metadata.session_id == "combined-thread"
    assert [candidate.thread_id for candidate in generation.candidates] == ["combined-thread"]
    assert generation.candidates[0].raw_path == str(tmp_path / "target-repo")
```

Add a frozen-oracle comparison covering session-meta changes, forks, subagents, malformed JSON, Unicode escapes, and function-call `workdir`. Add a worker-closure assertion that the combined worker imports no SQLite/store module.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
uv run pytest tests/test_session_generation.py tests/test_parser_aggregation.py tests/test_project_transition_evidence.py tests/test_spawn_sqlite_isolation.py -q
```

Expected: FAIL because `ParsedSessionGeneration` and `parse_session_generation` do not exist and current usage/candidate collectors open the file independently.

- [ ] **Step 3: Add generation value types**

```python
@dataclass(frozen=True, slots=True)
class RawRepoPathCandidate:
    raw_path: str
    timestamp: datetime
    thread_id: str
    source: str


@dataclass(frozen=True, slots=True)
class ParsedSessionGeneration:
    records: tuple[UsageRecord, ...]
    metadata: SessionMetadata
    candidates: tuple[RawRepoPathCandidate, ...]
```

Move the existing candidate dataclass to this module and re-export it from `project_transition_candidates.py` so existing imports remain source-compatible.

- [ ] **Step 4: Implement one streaming state machine**

Refactor `parser.py` so `parse_session_generation` owns the only `path.open("r", encoding="utf-8")` call. For each raw line:

1. use a union relevance gate covering existing usage markers plus response-item function calls;
2. decode and parse JSON once;
3. update existing usage/session state exactly as today;
4. update the candidate thread ID on `session_meta`;
5. extract only `response_item/function_call` `workdir` candidates; and
6. retain the first/root `session_meta` as `generation.metadata`, matching
   `read_session_metadata`, while later session-meta events may still update
   the current usage/candidate state; and
7. return immutable records, root metadata, and candidates.

Keep `parse_session_file` as:

```python
def parse_session_file(path: Path) -> list[UsageRecord]:
    return list(parse_session_generation(path).records)
```

Keep the candidate collector as a wrapper over the same generation scanner with its existing tenacity retry. Preserve existing malformed-JSON and retry behavior; an invalid complete generation remains a file error.

- [ ] **Step 5: Update the parallel worker result**

```python
@dataclass(frozen=True, slots=True)
class UsageParseResult:
    request: UsageParseRequest
    generation: ParsedSessionGeneration | None
    error: str
    span: WorkerSpan

    def __post_init__(self) -> None:
        if self.generation is not None and self.error:
            raise ValueError("usage parse result cannot contain a generation and an error")
```

`parse_usage_request` calls the retrying combined parser once. Update worker-isolation tests to scan the new module closure.

- [ ] **Step 6: Pass parser and worker tests**

```bash
uv run pytest tests/test_session_generation.py tests/test_parser_aggregation.py tests/test_parser_relevance_gate.py tests/test_project_transition_evidence.py tests/test_parallel_execution.py tests/test_spawn_sqlite_isolation.py tests/test_python_source_size.py -q
```

Expected: PASS with one open per combined parse and unchanged semantic fixtures.

- [ ] **Step 7: Commit combined parsing**

```bash
git add src/codex_usage/session_generation_models.py src/codex_usage/parser.py src/codex_usage/project_transition_candidates.py src/codex_usage/parallel/usage.py tests/test_session_generation.py tests/test_parser_aggregation.py tests/test_parser_relevance_gate.py tests/test_project_transition_evidence.py tests/test_spawn_sqlite_isolation.py
git commit -m "perf: parse usage and transition evidence once"
```

---

### Task 3: Atomic Usage And Candidate Generations

**Files:**
- Create: `src/codex_usage/session_cache_generations.py`
- Create: `tests/test_session_cache_generations.py`
- Modify: `src/codex_usage/session_cache_refresh.py`
- Modify: `src/codex_usage/session_cache_store.py`
- Modify: `src/codex_usage/session_cache_models.py`
- Modify: `tests/test_parallel_cache_recovery.py`
- Modify: `tests/test_session_cache.py`

**Interfaces:**
- Produces: `CacheRefreshOutcome(stats, usage_run, affected_task_ids)`.
- Produces: `replace_file_generation(connection, session_dirs, entry, generation) -> set[str]` returning old/new affected task IDs.
- Produces: `remove_candidate_generation(connection, file_key) -> set[str]`.
- Consumes: `UsageParseResult.generation` from Task 2.

- [ ] **Step 1: Write failing atomic-generation tests**

```python
def test_changed_file_replaces_usage_metadata_and_candidates_atomically(
    tmp_path: Path,
) -> None:
    corpus = write_transition_corpus(tmp_path)
    first = load_cached_session_data([corpus.sessions], cache_dir=corpus.cache)
    append_usage_and_new_workdir(corpus.changed_file)

    second = load_cached_session_data([corpus.sessions], cache_dir=corpus.cache)

    assert second.stats.files_parsed == 1
    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        assert connection.execute("select count(*) from transition_candidates").fetchone()[0] == 2
        assert connection.execute(
            "select count(*) from usage_records where file_key = ?", (corpus.thread_id,)
        ).fetchone()[0] == 2
```

Add tests that monkeypatch candidate verification/storage to fail and assert old usage, metadata, candidate rows, fingerprint, and transition dirty-task rows remain unchanged. Add a metadata test that fails if parent-side code reopens the JSONL.

- [ ] **Step 2: Run tests and verify current split storage fails**

```bash
uv run pytest tests/test_session_cache_generations.py tests/test_parallel_cache_recovery.py tests/test_session_cache.py -q
```

Expected: FAIL because candidate generations and affected-task results are not stored.

- [ ] **Step 3: Extract generation persistence from the oversized store module**

Create `session_cache_generations.py` with:

```python
def replace_file_generation(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    generation: ParsedSessionGeneration,
) -> set[str]:
    affected = affected_task_ids_for_file(connection, entry.file_key)
    delete_file_generation(connection, entry.file_key)
    insert_usage_records(connection, entry, generation.records)
    insert_session_metadata(connection, session_dirs, entry, generation)
    insert_transition_candidates(connection, entry.file_key, generation.candidates)
    upsert_file_fingerprint(connection, session_dirs, entry, generation.metadata.session_id)
    return affected | generation_task_ids(generation)


def affected_task_ids_for_file(
    connection: sqlite3.Connection,
    file_key: str,
) -> set[str]:
    return {
        task_id
        for task_id in query_generation_task_ids(connection, file_key)
        if task_id
    }
```

The affected set includes distinct session IDs from old usage rows, old candidates, the prior session-metadata row, new records, new candidates, and new metadata. Insert `timestamp_us` as integer UTC microseconds for both usage and candidate rows. Build the file summary only from `generation.metadata` and returned records; do not call `read_session_metadata`.

Move generation-specific private insert/delete helpers out of `session_cache_store.py` so both modules remain below 500 lines.

- [ ] **Step 4: Return affected task ownership from refresh**

Add:

```python
@dataclass(frozen=True, slots=True)
class CacheRefreshOutcome:
    stats: CacheStats
    usage_run: ParallelRunReport
    affected_task_ids: frozenset[str]
```

Change `refresh_files(connection, session_dirs, inventory, *, rebuilt, max_workers=None) -> CacheRefreshOutcome`. During preflight, capture task IDs before marking a disappeared file missing and delete its candidate generation. During each eight-result transaction, union affected IDs from successful replacements. Insert every affected non-empty task ID into `dirty_transition_tasks` in the same transaction.

Errors call the existing file-error path and preserve old generations. Infrastructure fallback behavior remains unchanged.

- [ ] **Step 5: Pass generation and recovery tests**

```bash
uv run pytest tests/test_session_cache_generations.py tests/test_parallel_cache_recovery.py tests/test_session_cache.py tests/test_parallel_cache_equivalence.py tests/test_python_source_size.py -q
```

Expected: PASS. Inspect `wc -l` and split again if `session_cache_store.py` or the new module reaches 500 lines.

- [ ] **Step 6: Commit atomic generations**

```bash
git add src/codex_usage/session_cache_generations.py src/codex_usage/session_cache_refresh.py src/codex_usage/session_cache_store.py src/codex_usage/session_cache_models.py tests/test_session_cache_generations.py tests/test_parallel_cache_recovery.py tests/test_session_cache.py
git commit -m "feat: persist complete cache generations"
```

---

### Task 4: Per-Task Incremental Project Transitions

**Files:**
- Create: `src/codex_usage/session_cache_queries.py`
- Create: `src/codex_usage/session_cache_transitions.py`
- Create: `tests/test_incremental_transitions.py`
- Modify: `src/codex_usage/session_cache.py`
- Modify: `src/codex_usage/session_cache_store.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `tests/test_cli_transitions.py`
- Modify: `tests/test_parallel_transition_equivalence.py`
- Modify: `tests/test_parallel_cache_equivalence.py`

**Interfaces:**
- Produces: `load_records_for_task_ids(connection, task_ids) -> list[UsageRecord]`.
- Produces: `load_raw_candidates_for_task_ids(connection, task_ids) -> list[RawRepoPathCandidate]`.
- Produces: `refresh_dirty_task_transitions(connection, session_dirs, *, auto_transitions) -> list[ProjectTransition]`.
- Produces: `load_cached_transition_observations(session_dirs, *, cache_dir=None) -> list[RepoPathObservation]` for `transitions suggest` without source rescanning.
- Consumes: `dirty_transition_tasks` and affected IDs from Task 3.

- [ ] **Step 1: Write failing incremental-transition tests**

```python
def test_one_changed_task_never_scans_unchanged_jsonl_for_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=6)
    load_cached_session_data([corpus.sessions], cache_dir=corpus.cache)
    append_transition(corpus.paths[2])

    opened: list[Path] = []
    monkeypatch.setattr(Path, "open", recording_open(Path.open, opened))
    refreshed = load_cached_session_data([corpus.sessions], cache_dir=corpus.cache)

    assert refreshed.stats.files_parsed == 1
    assert opened.count(corpus.paths[2]) == 1
    assert not set(corpus.paths[:2] + corpus.paths[3:]).intersection(opened)
    assert refreshed.transition_run.worker_spans == ()
```

Add tests for: automatic transitions disabled then enabled; candidate removal deleting only that task's transition; changed state observation for an affected task; failure retaining dirty task IDs; cold incremental output equality with `tests/project_transition_serial_oracle.py`.

- [ ] **Step 2: Run tests and verify global scan failure**

```bash
uv run pytest tests/test_incremental_transitions.py tests/test_cli_transitions.py tests/test_parallel_transition_equivalence.py -q
```

Expected: FAIL because dirty transition state is global and `collect_repo_path_observations_with_report` scans every session file.

- [ ] **Step 3: Add indexed task and candidate queries**

In `session_cache_queries.py`, implement chunked `IN` queries with at most 500 IDs per chunk:

```python
def load_records_for_task_ids(
    connection: sqlite3.Connection,
    task_ids: Collection[str],
) -> list[UsageRecord]:
    rows = query_rows_in_chunks(connection, "session_id", task_ids)
    return [row_to_usage_record(row) for row in rows]


def load_raw_candidates_for_task_ids(
    connection: sqlite3.Connection,
    task_ids: Collection[str],
) -> list[RawRepoPathCandidate]:
    rows = query_candidate_rows_in_chunks(connection, task_ids)
    return [row_to_raw_candidate(row) for row in rows]
```

Preserve deterministic ordering by `(file_key, record_index)` and `(file_key, candidate_index)`. Reuse one public row-to-record converter moved from `session_cache_store.py`; do not duplicate model conversion.

- [ ] **Step 4: Implement dirty-task transition ownership**

In `session_cache_transitions.py`:

```python
def refresh_dirty_task_transitions(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    *,
    auto_transitions: bool,
) -> list[ProjectTransition]:
    dirty_task_ids = load_dirty_task_ids(connection)
    if dirty_task_ids and auto_transitions:
        replace_dirty_task_transitions(connection, session_dirs, dirty_task_ids)
    return load_transitions(connection) if auto_transitions else []
```

Behavior:

1. return existing transitions when no dirty task exists;
2. retain dirty rows and return no automatic transitions when disabled;
3. load all records and raw candidates only for dirty task IDs;
4. verify candidates with one parent verification cache;
5. read `state_5.sqlite` once and filter observations to dirty IDs;
6. run `infer_project_transitions` on only those task records/observations;
7. in one immediate transaction, delete `project_transitions` by `owner_thread_id`, insert replacements with their sole owner ID, delete completed dirty rows, and commit;
8. roll back and retain dirty rows on failure.

Load and return all current transition rows after replacement because report tables are small. Set `CachedSessionData.transition_run` to `EMPTY_PARALLEL_RUN_REPORT`; transition JSONL work now belongs to the combined usage run.

- [ ] **Step 5: Remove report-time global source transition scans**

Replace `_refresh_or_load_transitions` in `session_cache.py` with the new module. Implement `load_cached_transition_observations` in `session_cache_transitions.py`; it resolves the cache directory, opens schema-4 SQLite read-only, loads/verifies cached raw candidates, adds current state observations, and returns the deterministic deduplicated list. Change `handle_transitions_suggest` to call this helper after `load_cached_session_data`; it must not call `collect_repo_path_observations(session_dirs, data.files)`.

Delete production calls to `collect_repo_path_observations_with_report` from the cache refresh path, but keep the serial collector and frozen oracle for equivalence tests.

- [ ] **Step 6: Pass transition and cache equivalence tests**

```bash
uv run pytest tests/test_incremental_transitions.py tests/test_cli_transitions.py tests/test_parallel_transition_equivalence.py tests/test_parallel_cache_equivalence.py tests/test_project_transition_detection.py tests/test_project_transition_evidence.py tests/test_python_source_size.py -q
```

Expected: PASS. A changed one-file fixture has one usage worker span and zero transition worker spans.

- [ ] **Step 7: Commit incremental transitions**

```bash
git add src/codex_usage/session_cache_queries.py src/codex_usage/session_cache_transitions.py src/codex_usage/session_cache.py src/codex_usage/session_cache_store.py src/codex_usage/cli.py tests/test_incremental_transitions.py tests/test_cli_transitions.py tests/test_parallel_transition_equivalence.py tests/test_parallel_cache_equivalence.py
git commit -m "perf: update project transitions per task"
```

---

### Task 5: Range-Aware SQLite Report Loading

**Files:**
- Create: `src/codex_usage/usage_context.py`
- Create: `tests/test_range_cache_queries.py`
- Modify: `src/codex_usage/aggregation.py`
- Modify: `src/codex_usage/parser.py`
- Modify: `src/codex_usage/session_cache.py`
- Modify: `src/codex_usage/session_cache_queries.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `tests/test_parallel_report_equivalence.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_parser_aggregation.py`

**Interfaces:**
- Produces: `RangeBounds(start_us: int | None, end_us: int | None)`.
- Produces: `resolve_range_bounds(range_name, timezone, now=None) -> RangeBounds`.
- Produces: `load_records_for_range(connection, selected_keys, bounds) -> list[UsageRecord]`.
- Changes: `load_cached_session_data(session_dirs, *, cache_dir=None, auto_transitions=True, max_workers=None, range_bounds: RangeBounds | None = None)`.
- Produces: `load_usage_context(args) -> UsageContext` in a focused module.

- [ ] **Step 1: Write failing range-query and parent-identity tests**

```python
def test_today_query_reads_only_today_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_three_day_parent_child_corpus(tmp_path)
    statements: list[str] = []
    connection = open_cache_with_trace(corpus, statements.append)
    bounds = resolve_range_bounds(
        "today", ZoneInfo("America/Toronto"), now=datetime(2026, 8, 3, 12, tzinfo=ZoneInfo("America/Toronto"))
    )

    records = load_records_for_range(connection, corpus.file_keys, bounds)

    assert {record.timestamp.date().isoformat() for record in records} == {"2026-08-03"}
    assert any("timestamp_us >=" in sql and "timestamp_us <" in sql for sql in statements)
    assert records[0].project_key == corpus.parent_project_key
```

Add exact oracle comparisons for all six ranges, UTC, America/Toronto spring/fall DST boundaries, a parent identity only outside the selected range, project transitions, missing retained rows, project filtering, subagents, and forks.

- [ ] **Step 2: Run range tests and verify full-table behavior fails**

```bash
uv run pytest tests/test_range_cache_queries.py tests/test_parallel_report_equivalence.py tests/test_cli.py -q
```

Expected: FAIL because bounds and indexed range queries do not exist and the loader executes `select * from usage_records`.

- [ ] **Step 3: Make range-bound resolution reusable**

Add:

```python
@dataclass(frozen=True, slots=True)
class RangeBounds:
    start_us: int | None
    end_us: int | None


def resolve_range_bounds(
    range_name: str,
    timezone: tzinfo,
    now: datetime | None = None,
) -> RangeBounds:
    start, end = resolve_local_range_datetimes(range_name, timezone, now)
    return RangeBounds(
        start_us=datetime_to_utc_microseconds(start) if start is not None else None,
        end_us=datetime_to_utc_microseconds(end) if end is not None else None,
    )
```

Use the existing local-midnight rules, convert each bound to UTC, then to integer microseconds. `all` returns both fields as `None`. Rewrite `filter_records_by_range` to use this function so direct-parse fallback and SQL share one boundary contract.

- [ ] **Step 4: Query only selected timestamps plus parent identities**

Implement `load_records_for_range` with four fixed query shapes: all, start-only, end-only, and bounded. Filter selected file keys without issuing thousands of SQL placeholders. Group rows by file key and preserve `(file_key, record_index)` order.

Collect non-empty `parent_thread_id` values from selected rows. Query authoritative parent identity rows with the session/timestamp index in 500-ID chunks. Extend `finalize_session_records` with an optional keyword-only `identity_records` iterable; those rows contribute to `identity_by_session` but are not emitted in the returned list.

- [ ] **Step 5: Move CLI context loading out of `cli.py`**

Create:

```python
@dataclass(frozen=True, slots=True)
class UsageContext:
    session_dirs: list[Path]
    files: list[Path]
    records: list[UsageRecord]
    timezone: tzinfo
    project_keys: list[str]
    project_transitions: list[ProjectTransition]
    storage_stats: CacheStats


def load_usage_context(args: argparse.Namespace) -> UsageContext:
    timezone = resolve_timezone(args.timezone or get_settings().timezone)
    bounds = resolve_range_bounds(args.range_name, timezone)
    data = load_session_data_for_context(args, bounds)
    return context_from_cached_data(args, data, timezone)
```

It resolves timezone and bounds before calling `load_cached_session_data`. The cache path returns already range-selected records; direct-parse fallback keeps full parsing followed by `filter_records_by_range`. Apply project transitions and project filters once, in the same semantic order as the current CLI.

Leave `threads` unbounded by passing `range_bounds=None`.

- [ ] **Step 6: Prove range equivalence and source freshness**

```bash
uv run pytest tests/test_range_cache_queries.py tests/test_parallel_report_equivalence.py tests/test_cli.py tests/test_cli_transitions.py tests/test_parser_aggregation.py tests/test_python_source_size.py -q
```

Expected: PASS, with SQL trace tests rejecting an unbounded `usage_records` query for non-`all` reports.

- [ ] **Step 7: Commit range-aware loading**

```bash
git add src/codex_usage/usage_context.py src/codex_usage/aggregation.py src/codex_usage/parser.py src/codex_usage/session_cache.py src/codex_usage/session_cache_queries.py src/codex_usage/cli.py tests/test_range_cache_queries.py tests/test_parallel_report_equivalence.py tests/test_cli.py tests/test_parser_aggregation.py
git commit -m "perf: query cached usage by report range"
```

---

### Task 6: Python Phase Timing Sidecar

**Files:**
- Create: `src/codex_usage/performance_timing.py`
- Create: `tests/test_performance_timing.py`
- Modify: `src/codex_usage/session_cache.py`
- Modify: `src/codex_usage/usage_context.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `src/codex_usage/parallel_audit.py`

**Interfaces:**
- Produces: `PhaseTimer.measure(name)` context manager and `elapsed_seconds(name)`.
- Produces: `write_timing_sidecar(path, timer, *, cache_stats, command) -> None`.
- Adds suppressed CLI option: `--timing-output PATH` to common usage commands.
- Sidecar schema: version 1, command, cache state/stats, phase seconds, and total seconds.

- [ ] **Step 1: Write failing timing and non-fatal-sidecar tests**

```python
def test_phase_timer_writes_versioned_atomic_sidecar(tmp_path: Path) -> None:
    clock = FakeClock([10.0, 10.2, 10.5, 11.0])
    timer = PhaseTimer(clock=clock)
    with timer.measure("inventory"):
        pass
    with timer.measure("range_query"):
        pass

    output = tmp_path / "timing.json"
    write_timing_sidecar(output, timer, cache_stats=CacheStats(), command="report")

    payload = json.loads(output.read_text())
    assert payload["version"] == 1
    assert payload["phases_seconds"] == {"inventory": 0.2, "range_query": 0.5}
    assert not (tmp_path / "timing.json.tmp").exists()
```

Add a CLI test that monkeypatches sidecar writing to raise `OSError`, then asserts the report still exits zero, writes HTML, and emits one warning to stderr.

- [ ] **Step 2: Run tests and verify missing instrumentation**

```bash
uv run pytest tests/test_performance_timing.py tests/test_cli.py -q
```

Expected: FAIL because timer types and `--timing-output` do not exist.

- [ ] **Step 3: Implement monotonic phase recording**

`PhaseTimer` accepts an injectable `Callable[[], float]` defaulting to `time.perf_counter`. Reject nested duplicate phase names and negative elapsed values. Round only during JSON serialization, not while accumulating.

Use the existing atomic-write pattern from `parallel_audit.py`: create a sibling temporary file, write UTF-8 JSON, then `Path.replace`. Decorate retryable write/replace I/O with three-attempt exponential backoff.

- [ ] **Step 4: Instrument exact boundaries**

Pass one timer through `usage_context` and `load_cached_session_data`. Measure exactly:

- `inventory`: session discovery/inventory only;
- `usage_refresh`: changed-file workers and generation commits;
- `transition_refresh`: dirty-task inference and replacement;
- `range_query`: bounded usage/parent lookup plus transition application;
- `aggregation_render`: report aggregation and HTML writing; and
- `total_cli`: handler start through successful output creation.

The sidecar includes `cache.rebuilt`, `cache.files_parsed`, `cache.files_reused`, and error/fallback counts. Do not print timing JSON to normal stdout.

- [ ] **Step 5: Pass timing and CLI tests**

```bash
uv run pytest tests/test_performance_timing.py tests/test_cli.py tests/test_parallel_report_equivalence.py tests/test_python_source_size.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit timing instrumentation**

```bash
git add src/codex_usage/performance_timing.py src/codex_usage/session_cache.py src/codex_usage/usage_context.py src/codex_usage/cli.py src/codex_usage/parallel_audit.py tests/test_performance_timing.py tests/test_cli.py
git commit -m "feat: report usage generation timings"
```

---

### Task 7: Latest-Request VS Code Refresh And Visible Load Time

**Files:**
- Create: `extensions/vscode/src/latestRefreshCoordinator.ts`
- Create: `extensions/vscode/test/latestRefreshCoordinator.test.js`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/src/dashboardWebview.ts`
- Modify: `extensions/vscode/test/core.test.js`
- Modify: `extensions/vscode/test/dashboardWebview.test.js`
- Modify: `extensions/vscode/test/syncProcess.test.js`

**Interfaces:**
- Produces: `LatestRefreshCoordinator<Request, Result>`.
- Produces: `request(value) -> Promise<"published" | "superseded">`.
- Extends: `ReportCommandOptions.timingOutputPath?: string`.
- Extends: `WebviewControlState.loadedSeconds?: number`.
- Uses cache-path functions from Task 1 to distinguish initializing, rebuilding, and refreshing copy.

- [ ] **Step 1: Write failing coordinator concurrency tests**

```javascript
test("latest refresh coordinator runs one process and publishes only newest request", async () => {
  const gates = deferredQueue();
  const running = [];
  const published = [];
  const coordinator = new LatestRefreshCoordinator(
    async (request) => {
      running.push(request);
      return gates.next(request).promise;
    },
    async (request, result) => published.push([request, result]),
  );

  const first = coordinator.request("today");
  const second = coordinator.request("yesterday");
  const third = coordinator.request("7d");
  assert.deepEqual(running, ["today"]);

  gates.resolve("today", "old");
  await tick();
  assert.deepEqual(running, ["today", "7d"]);
  gates.resolve("7d", "new");

  assert.equal(await first, "superseded");
  assert.equal(await second, "superseded");
  assert.equal(await third, "published");
  assert.deepEqual(published, [["7d", "new"]]);
});
```

Add tests for active failure followed by newer success, publish failure cleanup, and a later request after the coordinator becomes idle.

- [ ] **Step 2: Write failing timing/copy tests**

Assert:

```javascript
assert.match(html, /Loaded in 4\.2 seconds/);
assert.doesNotMatch(htmlWithoutTiming, /Loaded in/);
assert.deepEqual(buildReportArgs({
  range: "today",
  outputPath: "/tmp/report.html",
  timingOutputPath: "/tmp/timing.json",
}), [
  "report", "--range", "today", "--output", "/tmp/report.html",
  "--theme", "auto", "--timing-output", "/tmp/timing.json",
]);
```

Add loading-kind tests: no cache means `initializing`, legacy-only means `rebuilding`, schema-4 means `refreshing`.

- [ ] **Step 3: Run extension tests and verify failure**

```bash
cd extensions/vscode && npm test
```

Expected: FAIL because the coordinator, timing option, loading kind, and visible label do not exist.

- [ ] **Step 4: Implement the pure coordinator**

Use this public shape:

```typescript
export class LatestRefreshCoordinator<Request, Result> {
  constructor(
    execute: (request: Request) => Promise<Result>,
    publish: (request: Request, result: Result) => Promise<void> | void,
  );
  request(request: Request): Promise<"published" | "superseded">;
}
```

Keep one active request and one replaceable pending request. Resolve a replaced pending request as `superseded`. After execute, publish only when no newer generation exists. Use `finally` to clear active state and start the newest pending request. Never run execute concurrently.

- [ ] **Step 5: Extract dashboard execution from `extension.ts`**

Instantiate one coordinator during activation. The request snapshot contains panel, normalized settings, extension version, unique report path, unique timing path, and a monotonic request ID. The execute phase:

1. sets the appropriate initializing/rebuilding/refreshing HTML;
2. records `performance.now()`;
3. runs the bundled executable with `--timing-output`;
4. reads report HTML and optional timing JSON;
5. returns HTML, settings, elapsed seconds, and diagnostics without assigning `webview.html`.

The publish phase injects controls/CSP with `loadedSeconds`, assigns HTML, logs Python phases plus extension elapsed time, and updates status. Represent execution errors as result data so stale errors are discarded by the same publish gate. Only the latest error displays an error page/message.

All existing dashboard entry points call `coordinator.request(requestSnapshot)`. Do not add cancellation or file watchers. Move coordinator-specific types/helpers out of `extension.ts` if it would exceed 500 lines.

- [ ] **Step 6: Render accessible timing copy**

Add to `WebviewControlState` and render before the version:

```typescript
const loaded = Number.isFinite(state.loadedSeconds)
  ? `<span class="codex-usage-load-time">Loaded in ${state.loadedSeconds!.toFixed(1)} seconds</span>`
  : "";
```

Give timing/version a shared trailing metadata container so `margin-left: auto` applies once and narrow views wrap without overlap. No timer appears on loading or error documents.

- [ ] **Step 7: Pass extension tests**

```bash
cd extensions/vscode && npm test
```

Expected: all tests pass, including max process concurrency one and latest-only publication.

- [ ] **Step 8: Commit coordinated refresh UX**

```bash
git add extensions/vscode/src/latestRefreshCoordinator.ts extensions/vscode/src/extension.ts extensions/vscode/src/core.ts extensions/vscode/src/dashboardWebview.ts extensions/vscode/test/latestRefreshCoordinator.test.js extensions/vscode/test/core.test.js extensions/vscode/test/dashboardWebview.test.js extensions/vscode/test/syncProcess.test.js
git commit -m "feat: serialize dashboard refresh requests"
```

---

### Task 8: Acceptance Harness, ADR, Documentation, And Version 1.1.0

**Files:**
- Create: `scripts/parallel_cache_fixture.py`
- Modify: `scripts/parallel_cache_acceptance.py`
- Modify: `scripts/packaged_parallel_cache_smoke.py`
- Modify: `tests/test_parallel_acceptance_scripts.py`
- Modify: `tests/test_parallel_cache_docs.py`
- Modify: `tests/test_github_actions_workflow.py`
- Create: `docs/adr/0020-incremental-range-aware-usage-cache.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `src/codex_usage/__init__.py`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

**Interfaces:**
- Acceptance payload records cold, warm, and one-changed-file stats and timings.
- Packaged audit expects combined usage workers and zero transition worker spans.
- Release version is exactly `1.1.0` in all five version surfaces.

- [ ] **Step 1: Write failing acceptance-contract tests**

Require source and packaged scripts to assert:

```python
assert warm.stats.files_parsed == 0
assert len(warm.usage_run.worker_spans) == 0
assert len(warm.transition_run.worker_spans) == 0
assert changed.stats.files_parsed == 1
assert len(changed.usage_run.worker_spans) == 1
assert len(changed.transition_run.worker_spans) == 0
assert changed_semantic_digest == cold_after_same_append_digest
```

The changed phase appends one usage event and one function-call workdir to exactly one fixture. Its payload includes `source_bytes_eligible` equal to that changed file size, never total corpus size. `scripts/parallel_cache_fixture.py` exposes `write_parallel_cache_fixture(root: Path, *, file_count: int = 10, minimum_file_bytes: int = 2 * 1024 * 1024) -> FixtureCorpus`. `parallel_cache_acceptance.py --synthetic` creates a temporary directory, calls that function, and exercises it; `--synthetic` and `--sessions-dir` are mutually exclusive. The helper does not import from `tests` or write a fixture into the repository.

Add documentation tests requiring the phrases `schema 4`, `disposable derived data`, `one pass`, `per task`, `range-aware`, `Loaded in`, `latest request`, `complete file generation`, `macOS Apple Silicon`, and `Windows x64`.

- [ ] **Step 2: Run acceptance/doc tests and verify failure**

```bash
uv run pytest tests/test_parallel_acceptance_scripts.py tests/test_parallel_cache_docs.py tests/test_github_actions_workflow.py -q
```

Expected: FAIL because current scripts require a separate cold transition worker pool and do not exercise a one-file incremental refresh.

- [ ] **Step 3: Update source and frozen acceptance scripts**

Cold acceptance requires actual parallelism only from `usage_run`. Warm acceptance requires zero spans. Append to one fixture, rerun, require one usage span and no transition spans, and compare the incremental semantic digest with a separately rebuilt cold oracle after the same append.

Keep process-tree timeout ownership unchanged. Extend workflow tests so both native package jobs run the updated packaged smoke before VSIX creation.

- [ ] **Step 4: Write ADR 0020 and user documentation**

The ADR records:

- the 88.39 GiB full-transition-scan root cause;
- disposable schema 4 and one-time rebuild;
- combined per-file parsing;
- parent-owned candidate verification and SQLite;
- per-task dirty transition ownership;
- UTC-microsecond range queries with parent identity lookup;
- latest-request extension serialization; and
- rejected HTML caching, offsets, migration, and cancellation.

README copy explains that the first 1.1.0 report rebuilds the cache once, later reports inspect only changed files, and the toolbar shows elapsed load time. Do not promise a fixed number of seconds.

- [ ] **Step 5: Set every version surface to 1.1.0**

Update:

```text
pyproject.toml
src/codex_usage/__init__.py
uv.lock local package entry
extensions/vscode/package.json
extensions/vscode/package-lock.json root package entries
```

Add dated `1.1.0 - 2026-08-03` changelog sections without rewriting historical entries.

- [ ] **Step 6: Pass acceptance, docs, and version tests**

```bash
uv run pytest tests/test_parallel_acceptance_scripts.py tests/test_parallel_cache_docs.py tests/test_github_actions_workflow.py tests/test_release_history.py tests/test_task_transfer_docs.py -q
uv run python scripts/parallel_cache_acceptance.py --synthetic
```

Expected: PASS with cold/warm/changed JSON output.

- [ ] **Step 7: Commit release preparation**

```bash
git add scripts/parallel_cache_fixture.py scripts/parallel_cache_acceptance.py scripts/packaged_parallel_cache_smoke.py tests/test_parallel_acceptance_scripts.py tests/test_parallel_cache_docs.py tests/test_github_actions_workflow.py docs/adr/0020-incremental-range-aware-usage-cache.md docs/adr/README.md README.md extensions/vscode/README.md CHANGELOG.md extensions/vscode/CHANGELOG.md pyproject.toml src/codex_usage/__init__.py uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json
git commit -m "release: prepare incremental cache 1.1.0"
```

---

### Task 9: Full Verification, Review, And Native Package Gate

**Files:**
- Modify only files required by verified findings.
- Review: all changes from the design commit through Task 8.

**Interfaces:**
- Consumes all prior task interfaces.
- Produces a clean, review-ready `1.1.0` branch and dual-native package evidence.

- [ ] **Step 1: Run complete Python verification**

```bash
uv run pytest -q
uvx ruff check .
git diff --check
```

Expected: all tests pass, Ruff reports no findings, and `git diff --check` prints nothing.

- [ ] **Step 2: Run complete extension verification**

```bash
cd extensions/vscode
npm test
npm run test:registration-smoke
```

Expected: all Node/type tests and direct Codex registration smoke pass. Record existing `npm audit` findings separately; do not silently broaden this performance change into dependency remediation.

- [ ] **Step 3: Run source performance acceptance on the bounded corpus**

```bash
uv run python scripts/parallel_cache_acceptance.py --synthetic
```

Expected: cold parallel usage, warm zero spans, changed one span, no transition spans, and equal semantic digests.

- [ ] **Step 4: Build and smoke the macOS package locally**

```bash
cd extensions/vscode
npm run package:vsix:mac
```

Expected: PyInstaller arm64 binary, packaged parallel cache smoke, packaged Task Transfer smoke, registration gate, and VSIX creation all pass for version 1.1.0.

- [ ] **Step 5: Request two-stage code review**

Invoke `superpowers:requesting-code-review` with explicit focus on:

- accidental schema-3 compatibility branches;
- source JSONL double opens;
- incomplete usage/candidate transaction replacement;
- unchanged-file transition scans;
- incorrect per-task transition deletion;
- DST or parent-identity range errors;
- SQLite access from spawned workers;
- overlapping extension processes or stale result publication;
- timing instrumentation changing command success; and
- cross-platform cache path/version drift.

For every finding, invoke `superpowers:receiving-code-review`, reproduce it with one focused failing test, apply the contract-level fix, and rerun the focused plus complete suites.

- [ ] **Step 6: Run the manual non-publishing dual-native workflow**

Push the implementation branch, then run the existing `Package VSIX` workflow with publishing disabled against the exact branch SHA. Require both Windows x64 and macOS arm64 jobs to pass the updated packaged smoke and package version 1.1.0. Do not tag or publish in this step.

- [ ] **Step 7: Record verification evidence and final status**

```bash
git status --short --branch
git log -10 --oneline --decorate
```

Expected: clean worktree, intentional task commits, and the branch ready for merge/release approval.

Do not merge, tag, or publish until the user explicitly approves the verified implementation.
