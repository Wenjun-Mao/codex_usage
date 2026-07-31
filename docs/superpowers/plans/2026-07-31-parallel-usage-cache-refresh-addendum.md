# Parallel Usage Cache Refresh Addendum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cold and invalidated usage-cache refreshes complete reliably by parsing independent whole session files and extracting transition observations in a bounded process pool while preserving every existing usage and cache semantic.

**Architecture:** Keep discovery, cache classification, SQLite access, record finalization, transition inference, and deterministic ordering in the parent process. Spawn at most four read-only workers for complete-file parsing and JSONL transition scanning, return typed pickle-safe results, and replace complete file generations in fixed eight-file parent transactions so an interruption preserves earlier committed generations.

**Tech Stack:** Python 3.13, `concurrent.futures.ProcessPoolExecutor` with a `spawn` multiprocessing context, frozen dataclasses, tenacity, SQLite, pytest, PyInstaller 6.16+, uv, PowerShell, Bash, and GitHub Actions.

## Global Constraints

- This addendum begins after the measured failure in Task 3 of `docs/superpowers/plans/2026-07-31-usage-parser-performance-and-0-1-42-release.md`; original Tasks 1 and 2 and commits `b08eebb` and `c9b8d0f` remain accepted.
- Preserve exact parser, pricing, token-delta, aggregation, fork, parent-inheritance, subagent-inclusion, project-transition, and report outputs.
- Keep `CACHE_SCHEMA_VERSION = 3`, `PARSER_CACHE_VERSION = 2`, and `PROJECT_TRANSITION_CACHE_VERSION = 1`; add no table, column, index, trigger, or persisted generation field.
- Do not add range-based file pruning. A bounded report range is still applied only after complete current and retained cache records are loaded.
- Do not add within-file byte offsets, tail buffers, partial-line state, cumulative-token baselines, parser checkpoints, or append-only cache rows.
- Every selected generation is parsed by the unchanged `parse_session_file(path: Path) -> list[UsageRecord]` from byte zero through EOF.
- Workers may read session JSONL files and repository metadata only. Every SQLite open, read, transaction, replacement, transition write, and commit remains in the parent process, including `state_5.sqlite` reads.
- Use a deterministic default cap of four workers, further bounded by task count and available CPUs. One task, one available CPU, or process-pool failure uses the same top-level worker callable serially.
- Use fixed contiguous cache commit batches of eight inventory-ordered files. Do not hold a SQLite write transaction open while workers parse.
- Retain old successful usage and metadata rows until the full replacement tuple for that file has returned and its parent transaction commits.
- Exhausted worker file-read failures must retain the existing `"{ExceptionType}: {message}"` per-file cache error contract and must not delete prior successful rows.
- The supported frozen targets are macOS Apple Silicon (`darwin-arm64`) and Windows x64 (`win32-x64`). Both native package workflows must execute the parallel-cache smoke.
- No new dependency is required. Use the existing `tenacity` dependency for bounded retries of read-only session-file I/O, with `reraise=True` so final error text remains unchanged.
- Every Python source or test file created or modified by this addendum must end below 500 lines. Split the modified 767-line `session_cache.py`; do not add tests to a file that would reach 500 lines.
- Use `uv` for Python commands. Run focused tests at every RED/GREEN boundary and `uv run pytest -q` after the complete implementation.
- Version `0.1.42`, release date `2026-07-31`, Marketplace Preview status, and the original two-platform release gate remain unchanged.

---

## Root Cause And Scope

The failed acceptance stopped in cache refresh, before range filtering, aggregation, transition scanning, or rendering. The measured inventory contained 2,275 current files totaling about 69.65 GB, and all 2,275 failed the reuse predicate: 1,921 were new, 346 retained an error marker, seven had content-metadata changes, and one had moved. The optimized parser handled a representative 2.25 GB file in 6.228 seconds, but a serial refresh still had to traverse every selected byte. The single transaction committed only after the complete inventory loop, so interruption at 171 seconds rolled back every completed file.

Downstream cached-row materialization, range filtering, aggregation, and rendering were collectively small relative to the scan. Read-only prototypes over the four largest files reduced usage parsing from 21.49 seconds to 6.66 seconds and transition extraction from 9.65 seconds to 3.12 seconds with four processes; four threads did not improve the parser. These aggregate measurements locate the failure at serial whole-corpus traversal plus all-or-nothing transaction granularity. They do not justify changing usage semantics, trusting mtimes as timestamp upper bounds, or adding a new cache schema.

## Durable Contract

### Pickle-Safe Worker Interfaces

Create these top-level contracts. They contain only standard-library values and existing frozen dataclasses, have no connection, lock, closure, callback, or exception object, and must round-trip through `pickle.dumps`/`pickle.loads` under the `spawn` context.

```text
@dataclass(frozen=True, slots=True)
class UsageParseRequest:
    ordinal: int
    file_key: str
    path: Path
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class UsageParseResult:
    request: UsageParseRequest
    records: tuple[UsageRecord, ...] = ()
    error: str = ""


parse_usage_request(request: UsageParseRequest) -> UsageParseResult


@dataclass(frozen=True, slots=True)
class TransitionScanRequest:
    ordinal: int
    path: Path


@dataclass(frozen=True, slots=True)
class TransitionScanResult:
    request: TransitionScanRequest
    observations: tuple[RepoPathObservation, ...]


scan_transition_request(request: TransitionScanRequest) -> TransitionScanResult
```

`UsageParseResult.error` and `records` are mutually exclusive. `parse_usage_request` catches `Exception` only after bounded read retries and returns the existing formatted error; `KeyboardInterrupt`, `SystemExit`, and other `BaseException` values propagate. Expected transition per-file open/read failures continue to produce no observations, while an unexpected transition worker exception is retried serially by the process mapper and then propagates if it is reproducible.

### Bounded Execution Interface

```text
DEFAULT_MAX_WORKERS = 4
SERIAL_FALLBACK_WARNING = "process pool unavailable; continuing with serial whole-file workers"


resolve_worker_count(
    task_count: int,
    *,
    available_cpus: int | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> int


OrderedProcessMapper[RequestT, ResultT]
    __init__(
        self,
        worker: Callable[[RequestT], ResultT],
        *,
        task_count: int,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None

    @property
    worker_count: int

    @property
    used_serial_fallback: bool

    __enter__(self) -> OrderedProcessMapper[RequestT, ResultT]

    map_batch(self, requests: Sequence[RequestT]) -> list[ResultT]

    __exit__(self, exc_type: object, exc: object, traceback: object) -> None
```

`resolve_worker_count` returns zero for zero tasks and otherwise `min(task_count, max_workers, max(1, available_cpus or os.cpu_count() or 1))`. `OrderedProcessMapper` uses `multiprocessing.get_context("spawn")`. It submits one bounded caller-provided batch, collects futures in any completion order, and returns results in request order. If executor construction, submission, pickling, or result transport raises an `Exception`, it discards that read-only batch, shuts down the broken executor, emits `SERIAL_FALLBACK_WARNING` once, reruns the whole batch through the same top-level callable in the parent, and remains serial for later batches. It never catches `BaseException`.

### Parent Transaction And Ordering Contract

`collect_session_file_inventory` remains the ordering authority. The parent assigns each parse request its inventory ordinal and processes contiguous slices of eight. Worker activity occurs with no SQLite transaction open. After one complete result slice returns, the parent validates one result per request, sorts by ordinal defensively, begins `IMMEDIATE`, applies each complete success or per-file error, marks transitions dirty, and commits. Any insertion, validation, interruption, or commit-path exception rolls back the whole current slice; previous slices stay committed.

A successful replacement deletes and recreates that file's `usage_records` and `session_metadata` only inside this transaction, then updates its existing `files` row with the request's path, size, mtime, and a cleared error. A failed result calls the existing error behavior: update `last_seen_at` and `error` for an existing file without deleting its old child rows, or insert only an errored `files` row when no successful generation exists. Because the cached size and mtime come from the original inventory request, a file that grows during or after parsing mismatches the next inventory and is reparsed.

Final usage order remains inventory order plus sorted retained-missing keys, with each file in `record_index` order before unchanged `finalize_session_records`. Transition JSONL results are flattened by request ordinal, parent-only `state_5.sqlite` observations are appended, and the existing total observation dedupe/sort and `infer_project_transitions` sort run unchanged. Worker completion order therefore cannot affect records, transitions, evidence, or output digests.

### Why This Is Not An Incremental Append Checkpoint

The persisted unit is still one complete file generation. A worker always opens the selected path at byte zero and returns only after `parse_session_file` reaches EOF; the parent persists no offset, prior cumulative counter, partial line, tail hash, in-progress row, or worker state. An interruption leaves each file in exactly one of three existing states: the prior complete successful generation, a newly committed complete generation, or an errored file with any prior successful generation retained. Committing several complete-file replacements together changes transaction recovery granularity, not parser position or append semantics, so it does not violate the original plan's checkpoint prohibition.

## File And Function Map

| Path | Existing ownership | Planned ownership |
| --- | --- | --- |
| `src/codex_usage/parser.py` | `parse_session_file`, `finalize_session_records`, fork and parent identity rules | Read only; workers call these unchanged. |
| `src/codex_usage/session_inventory.py` | `collect_session_file_inventory`, path ordering, size/mtime generation | Read only; remains the parent request source. |
| `src/codex_usage/session_cache.py` | Public cache models plus schema, refresh, persistence, transitions, and loading | Shrink to the public facade and `load_cached_session_data`; re-export existing public names. |
| `src/codex_usage/session_cache_models.py` | New | `CacheStats`, `CachedFileSummary`, `CachedSessionData`, `CachedRowsSnapshot`. |
| `src/codex_usage/session_cache_schema.py` | New | Existing schema constants, create/match/rebuild/snapshot/restore functions; no schema edits. |
| `src/codex_usage/session_cache_store.py` | New | Parent-only SQLite generation replacement, error retention, row loading, summary loading, dirty flag, and atomic transition replacement. |
| `src/codex_usage/session_cache_refresh.py` | New | Reuse classification, parse requests, eight-file result transactions, and `CacheStats`. |
| `src/codex_usage/parallel/__init__.py` | New | Clean exports for process execution and worker contracts. |
| `src/codex_usage/parallel/execution.py` | New | Four-worker cap, spawn mapper, deterministic ordered results, serial fallback. |
| `src/codex_usage/parallel/usage.py` | New | `UsageParseRequest`, `UsageParseResult`, retry wrapper, top-level parse worker. |
| `src/codex_usage/project_transition_evidence.py` | Path extraction, JSONL scan, `state_5.sqlite` scan, dedupe | Keep path and JSONL evidence extraction; expose one-file scan and dedupe. Remove SQLite access. |
| `src/codex_usage/project_transition_state.py` | New | Parent-only read-only `state_5.sqlite` observation extraction. |
| `src/codex_usage/parallel/transitions.py` | New | Transition request/result and top-level one-file JSONL worker. |
| `src/codex_usage/project_transition_collection.py` | New | Ordered parallel JSONL orchestration plus parent state observations and final dedupe. |
| `src/codex_usage/project_transitions.py` | Transition inference/application and evidence re-export | Keep inference/application unchanged; re-export collection from the new module. |
| `src/codex_usage/cli.py` | Cache-first loader, direct-parse fallback, range filtering | Read only; `_load_session_data` and `_load_context` call order stays unchanged. |
| `src/codex_usage/__main__.py` | Frozen/source module entrypoint | Call `multiprocessing.freeze_support()` before importing CLI code. |
| `scripts/build-macos-arm64-exe.sh` | macOS PyInstaller build and packaged transfer smoke | Also run packaged parallel-cache smoke. |
| `scripts/build-windows-exe.ps1` | Windows PyInstaller build and packaged transfer smoke | Also run packaged parallel-cache smoke. |
| `.github/workflows/package-vsix.yml` | Native tests and package jobs on `macos-26`/`windows-2025` | Behavior unchanged; contract tests prove both package commands invoke the new smoke through build scripts. |

---

### Task 1: Spawn-Safe Bounded Process Mapper

**Files:**
- Create: `src/codex_usage/parallel/__init__.py`
- Create: `src/codex_usage/parallel/execution.py`
- Create: `tests/test_parallel_execution.py`

**Interfaces:**
- Produces: `resolve_worker_count(task_count, available_cpus, max_workers) -> int` and `OrderedProcessMapper[RequestT, ResultT]` exactly as specified above.
- Guarantees: at most four spawn workers, bounded caller batches, ordered return values, one warning and permanent serial mode after infrastructure failure, and no interception of `BaseException`.

- [ ] **Step 1: Write failing worker-count, ordering, overlap, fallback, and interruption tests**

Create top-level frozen probe request/result dataclasses and top-level probe workers in `tests/test_parallel_execution.py`. Cover these exact cases:

```python
def test_worker_count_is_bounded_and_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    assert resolve_worker_count(0) == 0
    assert resolve_worker_count(1) == 1
    assert resolve_worker_count(100) == 4
    assert resolve_worker_count(100, available_cpus=2) == 2
    assert resolve_worker_count(100, available_cpus=1) == 1


def test_process_mapper_returns_submission_order_after_reverse_completion() -> None:
    requests = [_ProbeRequest(ordinal=value, delay_rank=3 - value) for value in range(4)]
    with OrderedProcessMapper(_probe_worker, task_count=4, max_workers=2) as mapper:
        results = mapper.map_batch(requests)
    assert [result.ordinal for result in results] == [0, 1, 2, 3]


def test_process_mapper_overlaps_two_workers_without_elapsed_time_threshold() -> None:
    with multiprocessing.Manager() as manager:
        barrier = manager.Barrier(2)
        active = manager.Value("i", 0)
        peak = manager.Value("i", 0)
        lock = manager.Lock()
        requests = [_OverlapRequest(index, barrier, active, peak, lock) for index in range(2)]
        with OrderedProcessMapper(_overlap_worker, task_count=2, max_workers=2) as mapper:
            results = mapper.map_batch(requests)
        assert peak.value == 2
        assert len({result.pid for result in results}) == 2


def test_pool_bootstrap_failure_warns_once_and_stays_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", _FailingExecutor)
    with pytest.warns(RuntimeWarning, match=SERIAL_FALLBACK_WARNING) as warnings:
        with OrderedProcessMapper(_probe_worker, task_count=2, max_workers=2) as mapper:
            first = mapper.map_batch([_ProbeRequest(0, 0)])
            second = mapper.map_batch([_ProbeRequest(1, 0)])
            assert mapper.used_serial_fallback is True
    assert [result.ordinal for result in [*first, *second]] == [0, 1]
    assert len(warnings) == 1


def test_keyboard_interrupt_is_not_converted_to_serial_fallback() -> None:
    mapper = _mapper_with_interrupting_future()
    with pytest.raises(KeyboardInterrupt):
        mapper.map_batch([_ProbeRequest(0, 0)])
    assert mapper.used_serial_fallback is False
    assert mapper.serial_calls == 0
```

The overlap test uses synchronization counts, PIDs, and a barrier timeout only as deadlock protection; it contains no assertion that work finishes within a performance duration.

- [ ] **Step 2: Run the new tests and verify RED**

Run: `uv run pytest tests/test_parallel_execution.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'codex_usage.parallel'`.

- [ ] **Step 3: Implement the mapper with the exact default and fallback rules**

Use `ProcessPoolExecutor(max_workers=worker_count, mp_context=multiprocessing.get_context("spawn"))`, `submit`, and `as_completed`. Build a result list indexed by submission position. On an `Exception`, cancel pending futures, call `shutdown(wait=False, cancel_futures=True)`, set the executor to `None`, set `used_serial_fallback`, warn once, and recompute the complete current batch serially. On normal exit, call `shutdown(wait=True, cancel_futures=False)`; on a caller `BaseException`, cancel futures without converting it to fallback.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/test_parallel_execution.py -q`

Expected: PASS; the overlap assertion observes two active worker PIDs and the fallback test observes exactly one warning.

All probe dataclasses, workers, fake executors, fake futures, and mapper doubles named in this task live at module top level in `tests/test_parallel_execution.py`. Give them the exact fields used by the snippets (`ordinal`, `delay_rank`, `pid`, and the manager proxies), and do not add a production-only test hook.

- [ ] **Step 5: Commit the process mapper**

```bash
git add src/codex_usage/parallel/__init__.py src/codex_usage/parallel/execution.py tests/test_parallel_execution.py
git commit -m "feat: add bounded process worker runner"
```

### Task 2: Split Cache Models, Schema, And Parent Store

**Files:**
- Create: `src/codex_usage/session_cache_models.py`
- Create: `src/codex_usage/session_cache_schema.py`
- Create: `src/codex_usage/session_cache_store.py`
- Modify: `src/codex_usage/session_cache.py:1-767`
- Modify: `tests/test_session_cache.py:1-386`
- Modify: `tests/test_cli_transitions.py:1-265`
- Modify: `tests/test_python_source_size.py:9-15`

**Interfaces:**
- Preserves: imports of `CACHE_DB_NAME`, `CACHE_SCHEMA_VERSION`, `CacheStats`, `CachedFileSummary`, `CachedSessionData`, `load_cached_session_data`, `resolve_cache_dir`, and `uncached_session_data` from `codex_usage.session_cache`.
- Produces: parent-only `replace_file_generation(connection, session_dirs, entry, records)`, `record_file_error(connection, session_dirs, entry, error)`, cache row loaders, transition dirty helpers, and schema helpers with unchanged SQL.
- Constrains: `session_cache.py` and every new/modified Python file to fewer than 500 lines.

- [ ] **Step 1: Make the source-size contract fail for the cache facade**

Remove `"src/codex_usage/session_cache.py"` from `LEGACY_OVERSIZED_FILES` in `tests/test_python_source_size.py` and add this direct guard so RED does not depend on merge-base changed-file discovery:

```python
def test_session_cache_facade_stays_under_500_lines() -> None:
    path = REPOSITORY_ROOT / "src" / "codex_usage" / "session_cache.py"
    assert _line_count(path) < 500
```

Do not alter the exemptions for unrelated pre-existing oversized test modules.

- [ ] **Step 2: Run the size and cache suites and verify RED is structural only**

Run:

```bash
uv run pytest tests/test_python_source_size.py tests/test_session_cache.py tests/test_cli_transitions.py -q
```

Expected: `test_session_cache_facade_stays_under_500_lines` fails because `session_cache.py` has 767 lines; all cache and transition behavior tests pass.

- [ ] **Step 3: Move code without changing behavior or SQL**

Move the four frozen cache dataclasses to `session_cache_models.py`. Move constants and existing `_ensure_schema`, table creation/matching/drop, snapshot, restore, compatible-column insertion, and table-column helpers to `session_cache_schema.py`. Move existing record insertion/loading, summary insertion/loading, error retention, missing-file loading, transition dirty state, transition replacement, and transition loading to `session_cache_store.py`.

Expose these parent-store write signatures for Task 3:

```text
replace_file_generation(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    records: tuple[UsageRecord, ...],
) -> None


record_file_error(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    error: str,
) -> None
```

`replace_file_generation` must perform the existing delete/insert/summary/file-row operations without committing. `record_file_error` must preserve existing child rows and must not commit. Keep the five existing tables and every SQL column byte-for-byte equivalent; do not increment any version constant.

Keep `session_cache.py` as the facade that opens the one cache connection, calls schema/refresh/store functions, finalizes records, and returns `CachedSessionData`. Re-export the existing names so downstream sync imports do not change. Update tests that monkeypatch moved private helpers to patch `session_cache_schema` or `session_cache_store`, including schema restore failure, transition inference failure, and transition replacement interruption.

- [ ] **Step 4: Run cache, transition, sync-import, and size tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_python_source_size.py tests/test_session_cache.py tests/test_cli_transitions.py tests/test_sync_inventory.py tests/test_sync_selection_inventory_loading.py -q
```

Expected: PASS; `wc -l` reports fewer than 500 lines for all four modified/created cache modules, and schema-rebuild rollback tests still preserve child rows.

- [ ] **Step 5: Commit the behavior-preserving split**

```bash
git add src/codex_usage/session_cache.py src/codex_usage/session_cache_models.py src/codex_usage/session_cache_schema.py src/codex_usage/session_cache_store.py tests/test_session_cache.py tests/test_cli_transitions.py tests/test_python_source_size.py
git commit -m "refactor: split usage cache persistence"
```

### Task 3: Parallel Whole-File Parse And Atomic Batch Refresh

**Files:**
- Create: `src/codex_usage/parallel/usage.py`
- Create: `src/codex_usage/session_cache_refresh.py`
- Modify: `src/codex_usage/parallel/__init__.py`
- Modify: `src/codex_usage/session_cache.py`
- Create: `tests/test_parallel_usage_workers.py`
- Create: `tests/test_session_cache_parallel.py`
- Modify: `tests/test_session_cache.py:34-385`

**Interfaces:**
- Consumes: `OrderedProcessMapper`, unchanged `parse_session_file`, inventory entries, and parent-only store functions from Tasks 1-2.
- Produces: `UsageParseRequest`, `UsageParseResult`, `parse_usage_request`, `CACHE_COMMIT_BATCH_SIZE = 8`, and `refresh_files(connection, session_dirs, inventory, rebuilt, max_workers) -> CacheStats`.
- Preserves: the cache reuse predicate, stats meanings, error text, old-row fallback, missing retention, transition dirty behavior, record order, and schema.

- [ ] **Step 1: Write failing pickle, semantic-equivalence, worker-error, recovery, and invalidation tests**

In `tests/test_parallel_usage_workers.py`, create mixed fixtures containing normal usage, parent/subagent inheritance, fork replay, malformed candidates, Unicode-escaped relevant event names, an empty valid file, and invalid UTF-8. Assert:

```python
def test_usage_worker_contract_round_trips_through_pickle(tmp_path: Path) -> None:
    request = UsageParseRequest(0, "thread-1", path, path.stat().st_size, path.stat().st_mtime_ns)
    assert pickle.loads(pickle.dumps(request)) == request
    result = parse_usage_request(request)
    assert pickle.loads(pickle.dumps(result)) == result


def test_parallel_file_results_finalize_exactly_like_serial_parser(tmp_path: Path) -> None:
    serial_by_file = [parse_session_file(path) for path in ordered_valid_paths]
    parallel_by_file = [list(result.records) for result in ordered_worker_results]
    assert parallel_by_file == serial_by_file
    assert finalize_session_records(parallel_by_file) == finalize_session_records(serial_by_file)


def test_worker_exception_uses_existing_per_file_error_text(tmp_path: Path) -> None:
    result = parse_usage_request(invalid_utf8_request)
    assert result.records == ()
    assert result.error.startswith("UnicodeDecodeError: ")
```

In `tests/test_session_cache_parallel.py`, add these exact behavioral tests:

- `test_reverse_worker_completion_keeps_inventory_and_record_order`
- `test_worker_failure_retains_previous_complete_generation_and_retries`
- `test_insertion_failure_rolls_back_complete_eight_file_batch`
- `test_interruption_after_first_batch_reuses_eight_committed_generations`
- `test_file_growth_after_worker_parse_invalidates_next_inventory`
- `test_parallel_refresh_keeps_schema_versions_and_columns_unchanged`
- `test_workers_never_receive_a_sqlite_connection`

The interruption test creates nine cold files, returns the first eight complete results, raises `KeyboardInterrupt` before the second batch, then reopens the cache and asserts `files_reused == 8`, `files_parsed == 1`, exact totals for all nine files, and no duplicate rows. The insertion-failure test raises after a child-row delete inside one batch and asserts rollback restores every old generation in that batch.

Define `_write_parallel_usage_fixture(tmp_path: Path) -> tuple[list[Path], Path]` in `tests/test_parallel_usage_workers.py`; it returns inventory-ordered valid paths plus the invalid UTF-8 path. Keep every cache transaction fixture in `tests/test_session_cache_parallel.py` so neither test module imports a private helper from another test module.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/test_parallel_usage_workers.py tests/test_session_cache_parallel.py -q
```

Expected: collection fails because `codex_usage.parallel.usage` and `codex_usage.session_cache_refresh` do not exist.

- [ ] **Step 3: Implement the pickle-safe worker with bounded read retry**

Use this retry boundary and final exception mapping:

```python
@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def _parse_session_file_with_retry(path: Path) -> list[UsageRecord]:
    return parse_session_file(path)


def parse_usage_request(request: UsageParseRequest) -> UsageParseResult:
    try:
        records = _parse_session_file_with_retry(request.path)
    except Exception as exc:
        return UsageParseResult(request=request, error=f"{type(exc).__name__}: {exc}")
    return UsageParseResult(request=request, records=tuple(records))
```

Reject an invalid `UsageParseResult` containing both records and an error in `__post_init__`. Do not catch `BaseException` and do not import `sqlite3` in `parallel/usage.py`.

- [ ] **Step 4: Implement parent classification and complete-file batch commits**

Use this exact signature:

```text
CACHE_COMMIT_BATCH_SIZE = 8


refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> CacheStats
```

Perform one short parent preflight transaction to mark missing rows, touch reusable rows, and set transition dirty for rebuild/missing changes. Build requests only for entries that fail the exact existing path/size/mtime/missing/error predicate. Open one `OrderedProcessMapper(parse_usage_request, task_count=len(requests), max_workers=max_workers)`, pass contiguous `itertools.batched(requests, 8)` slices to `map_batch`, validate and ordinal-sort each complete result slice, then open one `BEGIN IMMEDIATE` transaction per slice.

Inside a slice transaction, call `replace_file_generation` for success or `record_file_error` for failure, set transition dirty, and commit. Catch `BaseException`, roll back, and re-raise. Increment returned stats only for committed slices; `files_parsed` continues to count attempted files including per-file errors. The public `load_cached_session_data` calls `refresh_files` without overriding `max_workers`.

- [ ] **Step 5: Run focused cache and semantic suites and verify GREEN**

Run:

```bash
uv run pytest tests/test_parallel_execution.py tests/test_parallel_usage_workers.py tests/test_session_cache_parallel.py tests/test_session_cache.py tests/test_parser_aggregation.py tests/test_parser_relevance_gate.py tests/test_session_provenance.py tests/test_token_usage.py tests/test_pricing.py -q
```

Expected: PASS with serial/parallel equality, eight committed files reusable after interruption, old records retained on error, and unchanged fork/subagent/pricing totals.

- [ ] **Step 6: Commit parallel cache refresh**

```bash
git add src/codex_usage/parallel/__init__.py src/codex_usage/parallel/usage.py src/codex_usage/session_cache.py src/codex_usage/session_cache_refresh.py tests/test_parallel_usage_workers.py tests/test_session_cache_parallel.py tests/test_session_cache.py
git commit -m "perf: refresh usage cache in parallel batches"
```

### Task 4: Parallel Transition Observation Extraction With Parent SQLite

**Files:**
- Modify: `src/codex_usage/project_transition_evidence.py:1-417`
- Create: `src/codex_usage/project_transition_state.py`
- Create: `src/codex_usage/parallel/transitions.py`
- Create: `src/codex_usage/project_transition_collection.py`
- Modify: `src/codex_usage/project_transitions.py:7-11`
- Modify: `src/codex_usage/parallel/__init__.py`
- Create: `tests/test_parallel_project_transition_evidence.py`
- Modify: `tests/test_project_transition_evidence.py:1-335`

**Interfaces:**
- Produces: `collect_jsonl_file_observations(path: Path) -> list[RepoPathObservation]`, `dedupe_repo_path_observations(observations) -> list[RepoPathObservation]`, `collect_state_repo_path_observations(session_dirs)`, transition worker contracts, and unchanged public `collect_repo_path_observations(session_dirs, session_files)`.
- Guarantees: workers scan JSONL only; parent reads `state_5.sqlite`; final observations and inferred transitions equal serial extraction exactly.

- [ ] **Step 1: Write failing transition pickle, ordering, parent-SQLite, and equivalence tests**

Create fixtures spanning multiple files, duplicate paths, malformed JSON, invalid UTF-8, Windows/POSIX paths, function-call arguments, user-message decoys, and one `state_5.sqlite` row. Define `_write_parallel_transition_fixture(tmp_path: Path) -> tuple[list[Path], list[Path], list[UsageRecord], list[RepoPathObservation], list[ProjectTransition]]` in the same test module. Define `ReverseResultMapper` there as a context manager whose `map_batch` calls `scan_transition_request` for every request and returns the complete results in reverse order; this is a parent-side ordering double, not a production hook. Add:

```python
def test_transition_worker_contract_round_trips_through_pickle(tmp_path: Path) -> None:
    path = tmp_path / "thread.jsonl"
    path.write_text("", encoding="utf-8")
    request = TransitionScanRequest(ordinal=0, path=path)
    assert pickle.loads(pickle.dumps(request)) == request
    result = scan_transition_request(request)
    assert pickle.loads(pickle.dumps(result)) == result


def test_parallel_and_serial_transition_observations_are_exactly_equal(tmp_path: Path) -> None:
    expected_jsonl = [
        observation
        for path in session_files
        for observation in collect_jsonl_file_observations(path)
    ]
    expected = dedupe_repo_path_observations(
        [*expected_jsonl, *collect_state_repo_path_observations(session_dirs)]
    )
    assert collect_repo_path_observations(session_dirs, session_files) == expected


def test_reverse_transition_worker_completion_keeps_observation_and_inference_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dirs, session_files, records, serial_observations, serial_transitions = (
        _write_parallel_transition_fixture(tmp_path)
    )
    monkeypatch.setattr(collection_module, "OrderedProcessMapper", ReverseResultMapper)
    actual = collect_repo_path_observations(session_dirs, session_files)
    assert actual == serial_observations
    assert infer_project_transitions(records, actual) == serial_transitions


def test_state_sqlite_is_opened_only_in_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dirs, session_files, _records, _observations, _transitions = (
        _write_parallel_transition_fixture(tmp_path)
    )
    parent_pid = os.getpid()
    connect_pids: list[int] = []
    original_connect = state_module.sqlite3.connect
    monkeypatch.setattr(
        state_module.sqlite3,
        "connect",
        lambda *args, **kwargs: (connect_pids.append(os.getpid()), original_connect(*args, **kwargs))[1],
    )
    collection_module._collect_repo_path_observations(
        session_dirs,
        session_files,
        max_workers=2,
    )
    assert connect_pids
    assert set(connect_pids) == {parent_pid}
```

- [ ] **Step 2: Run transition tests and verify RED**

Run: `uv run pytest tests/test_parallel_project_transition_evidence.py -q`

Expected: collection fails because the new state, collection, and worker modules do not exist.

- [ ] **Step 3: Separate JSONL evidence from state SQLite and add the worker**

Move all `state_5.sqlite` functions to `project_transition_state.py`; retain read-only URI mode and existing missing/schema/error behavior. Wrap transient `sqlite3.OperationalError` reads with three tenacity attempts and `reraise=True`, then preserve the existing final empty-observation behavior. The module is imported and called only by the parent collection module.

Refactor the current JSONL loop into `collect_jsonl_file_observations(path)`, retaining `errors="ignore"`, source filtering, path verification, and file-local verification caching. `scan_transition_request` calls only that function and returns a tuple. It imports neither `sqlite3` nor the state module.

- [ ] **Step 4: Implement deterministic collection and unchanged inference input**

Use `TRANSITION_SCAN_BATCH_SIZE = 16`. Assign ordinals from the existing `session_files` order, reuse one bounded mapper, flatten ordinal-sorted result batches, append parent state observations, and call the extracted existing dedupe/sort once. Keep this public signature unchanged:

```text
collect_repo_path_observations(
    session_dirs: list[Path],
    session_files: list[Path],
) -> list[RepoPathObservation]
```

Keep a private `_collect_repo_path_observations(session_dirs, session_files, *, max_workers: int)` entry for deterministic serial/parallel tests. Re-export the public function from `project_transitions.py`; do not change `infer_project_transitions` or `_observation_sort_key`.

- [ ] **Step 5: Run transition, cache, and CLI equivalence suites and verify GREEN**

Run:

```bash
uv run pytest tests/test_parallel_project_transition_evidence.py tests/test_project_transition_evidence.py tests/test_project_transition_detection.py tests/test_project_transitions.py tests/test_cli_transitions.py tests/test_session_cache_parallel.py -q
```

Expected: PASS; parallel and serial observations and `ProjectTransition` objects compare exactly, and tracked SQLite opens all use the parent PID.

- [ ] **Step 6: Commit parallel transition scanning**

```bash
git add src/codex_usage/project_transition_evidence.py src/codex_usage/project_transition_state.py src/codex_usage/project_transition_collection.py src/codex_usage/project_transitions.py src/codex_usage/parallel/__init__.py src/codex_usage/parallel/transitions.py tests/test_parallel_project_transition_evidence.py tests/test_project_transition_evidence.py
git commit -m "perf: scan project transitions in parallel"
```

### Task 5: PyInstaller Freeze Support And Native No-Recursion Smoke

**Files:**
- Modify: `src/codex_usage/__main__.py:1-7`
- Create: `scripts/smoke-test-packaged-parallel-cache.py`
- Modify: `scripts/build-macos-arm64-exe.sh:7-38`
- Modify: `scripts/build-windows-exe.ps1:6-43`
- Create: `tests/test_packaged_parallel_cache_smoke.py`
- Modify: `tests/test_github_actions_workflow.py:17-93`

**Interfaces:**
- Produces: early `freeze_support()` dispatch and one native executable smoke used by both package scripts.
- Verifies: a frozen parallel cold refresh and transition scan complete without recursive CLI startup or serial-fallback warning on macOS arm64 and Windows x64.

- [ ] **Step 1: Write failing entrypoint and workflow contract tests**

Assert the entrypoint contains `freeze_support()` inside the `__main__` guard before `from codex_usage.cli import main`. Assert each native build script invokes both `smoke-test-packaged-sync.py` and `smoke-test-packaged-parallel-cache.py`. Assert the `windows-2025` and `macos-26` workflow jobs run their package command, which reaches the corresponding build script.

In `tests/test_packaged_parallel_cache_smoke.py`, import the smoke module and test its fixture creation and payload validator with a subprocess double. Require nine session files, exact total tokens, at least one inferred transition, a nonempty cache, and rejection of stderr containing `SERIAL_FALLBACK_WARNING`.

- [ ] **Step 2: Run static/package-smoke tests and verify RED**

Run:

```bash
uv run pytest tests/test_packaged_parallel_cache_smoke.py tests/test_github_actions_workflow.py -q
```

Expected: FAIL because `freeze_support` and the packaged parallel-cache smoke are absent.

- [ ] **Step 3: Make the frozen entrypoint dispatch multiprocessing first**

Implement exactly:

```python
from __future__ import annotations

from multiprocessing import freeze_support


if __name__ == "__main__":
    freeze_support()
    from codex_usage.cli import main

    raise SystemExit(main())
```

The deferred CLI import prevents frozen worker bootstrap from recursively constructing the argument parser or opening the cache.

- [ ] **Step 4: Implement and wire the native smoke**

The smoke creates an isolated temporary `CODEX_HOME`, cache directory, source repository, and target repository; writes nine deterministic JSONLs with usage followed by function-call workdir evidence; and invokes the provided executable twice with `summary --range all --json`. Use `subprocess.run(command, env=environment, timeout=120, check=False, capture_output=True, text=True)` as a recursion deadlock guard, not a performance assertion.

Validate both runs return zero, parse one JSON object, report exact identical totals and transitions, and do not emit `SERIAL_FALLBACK_WARNING`. Query the isolated cache from the outer smoke process and require nine successful `files` rows, no file errors, and transition rows. The first invocation exercises spawn parsing and transition scanning; the second proves warm reuse. Keep the script below 500 lines and do not use `assert` in production smoke validation; raise `RuntimeError` with exact failed-contract messages.

Call the script after PyInstaller creates the executable and before the existing packaged transfer smoke in both native build scripts.

- [ ] **Step 5: Run source tests and the available native package workflow**

Run on every host:

```bash
uv run pytest tests/test_packaged_parallel_cache_smoke.py tests/test_github_actions_workflow.py tests/test_parallel_execution.py -q
```

Expected: PASS.

Run on macOS Apple Silicon:

```bash
bash scripts/build-macos-arm64-exe.sh
```

Run on Windows x64:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-windows-exe.ps1
```

Expected on each supported host: PyInstaller succeeds, the packaged parallel-cache smoke completes both invocations with no fallback warning, and the existing packaged Task Transfer smoke passes. A developer host runs only its matching native command; both commands are mandatory in the `macos-26` and `windows-2025` release jobs.

- [ ] **Step 6: Commit frozen multiprocessing coverage**

```bash
git add src/codex_usage/__main__.py scripts/smoke-test-packaged-parallel-cache.py scripts/build-macos-arm64-exe.sh scripts/build-windows-exe.ps1 tests/test_packaged_parallel_cache_smoke.py tests/test_github_actions_workflow.py
git commit -m "test: cover frozen parallel cache workers"
```

### Task 6: ADR 0019 Concurrency And Recovery Contract

**Files:**
- Create: `docs/adr/0019-bounded-parallel-cache-refresh.md`
- Modify: `docs/adr/README.md:7-29`
- Create: `tests/test_parallel_cache_docs.py`

**Interfaces:**
- Produces: durable rationale for worker bounds, parent SQLite ownership, complete-generation transactions, deterministic ordering, serial fallback, and the no-checkpoint distinction.

- [ ] **Step 1: Write the failing ADR contract test**

Require ADR 0019 and the ADR index to contain the exact concepts `four`, `parent process`, `complete file generation`, `eight`, `serial fallback`, `deterministic`, `no byte offset`, `schema version 3`, `macOS Apple Silicon`, and `Windows x64`.

Run: `uv run pytest tests/test_parallel_cache_docs.py -q`

Expected: FAIL because ADR 0019 does not exist.

- [ ] **Step 2: Write concise ADR 0019**

Use these sections and decisions, in concise prose rather than implementation chronology:

```markdown
# ADR 0019: Bounded Parallel Usage Cache Refresh

## Status
Accepted

## Context
Record the aggregate zero-reuse 69.65 GB failure, the 171-second rollback, negligible downstream work, and the measured four-process improvement without identifying local files or projects.

## Decision
Parse complete files and scan JSONL transition evidence with at most four spawn workers. Keep discovery, all SQLite access including state_5.sqlite, deterministic ordering, finalization, inference, and writes in the parent. Commit fixed eight-file batches of complete generations, retain old successful rows until replacement commit, warn and continue serially when process startup or transport fails, and keep schema version 3.

## Rejected Alternatives
Reject threads based on measured behavior; reject range pruning because start/mtime are not timestamp upper bounds; reject transition-evidence caching because it changes schema; reject byte-offset append checkpoints because they add partial parser state.

## Consequences And Guardrails
An interruption reuses committed complete generations and retries only uncommitted/error files. Output is independent of completion order. No byte offset or partial generation is persisted. Spawn/freeze smoke is required on macOS Apple Silicon and Windows x64, and serial/parallel equivalence plus recovery tests guard the contract.
```

Replace the final standalone ADR 0018 sentence in `docs/adr/README.md` with indexed rows for ADRs 0018 and 0019.

- [ ] **Step 3: Run ADR and source-size tests and verify GREEN**

Run: `uv run pytest tests/test_parallel_cache_docs.py tests/test_python_source_size.py -q`

Expected: PASS.

- [ ] **Step 4: Commit the ADR**

```bash
git add docs/adr/0019-bounded-parallel-cache-refresh.md docs/adr/README.md tests/test_parallel_cache_docs.py
git commit -m "docs: record parallel cache recovery contract"
```

### Task 7: Full Verification And Aggregate-Only Cold-Cache Acceptance

**Files:**
- Verify: all modified source, tests, scripts, ADRs, and workflows
- Temporary cache: an automatically deleted directory outside normal `CODEX_HOME`
- Record aggregate results: `.superpowers/sdd/2026-07-31-usage-parser-performance-and-0-1-42-release/parallel-cache-refresh-implementation-report.md`

**Interfaces:**
- Verifies: exact source semantics, operation-count concurrency, batch recovery, source-size limits, and one real cold/warm cache cycle.
- Records: corpus file/byte counts, worker count, elapsed observations, cache stats, record/transition counts, and digests only; no paths, IDs, project names, event text, or row contents.

- [ ] **Step 1: Run formatting-independent repository and focused contract checks**

Run:

```bash
git diff --check
uv run pytest tests/test_parallel_execution.py tests/test_parallel_usage_workers.py tests/test_session_cache_parallel.py tests/test_parallel_project_transition_evidence.py tests/test_packaged_parallel_cache_smoke.py tests/test_parallel_cache_docs.py tests/test_python_source_size.py -q
```

Expected: PASS with no whitespace errors and no changed/new Python file at or above 500 lines.

- [ ] **Step 2: Run the complete Python suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 3: Run aggregate-only cold and warm acceptance on quiescent local sessions**

Stop writes to local Codex sessions for the duration, then run this harness. It intentionally has no elapsed-time assertion:

```bash
uv run python - <<'PY'
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from time import perf_counter

from codex_usage.parallel import resolve_worker_count
from codex_usage.session_cache import load_cached_session_data
from codex_usage.session_inventory import collect_session_file_inventory, find_session_dirs


def digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


session_dirs = find_session_dirs()
inventory = collect_session_file_inventory(session_dirs)
with tempfile.TemporaryDirectory(prefix="codex-usage-parallel-cold-") as temporary:
    cache_dir = Path(temporary)
    started = perf_counter()
    cold = load_cached_session_data(session_dirs, cache_dir=cache_dir, auto_transitions=True)
    cold_seconds = perf_counter() - started

    started = perf_counter()
    warm = load_cached_session_data(session_dirs, cache_dir=cache_dir, auto_transitions=True)
    warm_seconds = perf_counter() - started

    assert cold.stats.files_reused == 0
    assert cold.stats.files_parsed == cold.stats.files_current
    assert warm.stats.files_parsed == cold.stats.file_errors
    assert warm.stats.files_reused + warm.stats.files_parsed == warm.stats.files_current
    assert warm.records == cold.records
    assert warm.project_transitions == cold.project_transitions

    print(json.dumps({
        "corpus": {
            "files": len(inventory),
            "bytes": sum(entry.size_bytes for entry in inventory),
            "workers": resolve_worker_count(len(inventory)),
        },
        "cold": {
            "seconds": round(cold_seconds, 3),
            "files_parsed": cold.stats.files_parsed,
            "files_reused": cold.stats.files_reused,
            "file_errors": cold.stats.file_errors,
            "records": len(cold.records),
            "transitions": len(cold.project_transitions),
            "records_digest": digest(cold.records),
            "transitions_digest": digest(cold.project_transitions),
        },
        "warm": {
            "seconds": round(warm_seconds, 3),
            "files_parsed": warm.stats.files_parsed,
            "files_reused": warm.stats.files_reused,
            "file_errors": warm.stats.file_errors,
            "records_digest": digest(warm.records),
            "transitions_digest": digest(warm.project_transitions),
        },
    }, sort_keys=True))
PY
```

Expected: one aggregate JSON object; cold attempts every current file with the resolved worker count, warm reuses every successful generation and retries only cold error rows, and cold/warm digests match. Record the observed cold and warm times in the implementation report and compare them on the same machine/corpus with the prior 171-second interrupted run. Timing is a measured release judgment, not a CI assertion. If the run does not complete materially better, stop release preparation and write a new aggregate diagnostic rather than weakening this contract.

- [ ] **Step 4: Verify scope and write the implementation report**

Record task commits, test commands/results, both native package outcomes, aggregate cold/warm JSON, and any residual concern. Confirm `src/codex_usage/parser.py`, `aggregation.py`, `pricing.py`, `session_provenance.py`, cache schema SQL, and CLI range ordering have no semantic changes. Do not include local paths, session IDs, project labels, or event samples.

No commit is created for the ignored implementation report.

### Task 8: Return To Original Task 3 And Prepare 0.1.42

**Files:**
- Resume: `docs/superpowers/plans/2026-07-31-usage-parser-performance-and-0-1-42-release.md:244-568`
- Read: `/tmp/codex-usage-parser-baseline.json`
- Read: `/tmp/codex-usage-parser-fixtures/`
- Temporary report: `/tmp/codex-usage-7d-performance.html`
- Then modify only the release files listed in original Task 4.

**Interfaces:**
- Consumes: all passing addendum gates and the parser digests captured by original Task 1.
- Produces: completed original Task 3 acceptance, then preview `0.1.42` release preparation and publication under original Tasks 4-5.

- [ ] **Step 1: Re-run the original parser digest equivalence gate**

Run:

```bash
uv run python - <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from codex_usage.parser import parse_session_file

baseline = json.loads(
    Path("/tmp/codex-usage-parser-baseline.json").read_text(encoding="utf-8")
)
mismatches = []
for row in baseline:
    path = Path(row["path"])
    if not path.is_file():
        mismatches.append((str(path), "missing"))
        continue
    actual = hashlib.sha256(repr(parse_session_file(path)).encode("utf-8")).hexdigest()
    if actual != row["digest"]:
        mismatches.append((str(path), actual))
assert not mismatches, mismatches[:5]
print(f"equivalent={len(baseline)}")
PY
```

Expected: `equivalent=100` on the measured dataset, or the exact smaller captured count, with no mismatch.

- [ ] **Step 2: Re-run the largest-file and real seven-day report observations**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
from time import perf_counter

from codex_usage.parser import parse_session_file

paths = list((Path.home() / ".codex" / "sessions").rglob("*.jsonl"))
largest = max(paths, key=lambda path: path.stat().st_size)
started = perf_counter()
records = parse_session_file(largest)
elapsed = perf_counter() - started
print({
    "size_bytes": largest.stat().st_size,
    "records": len(records),
    "seconds": round(elapsed, 3),
})
PY

/usr/bin/time -p uv run codex-usage report --range 7d --output /tmp/codex-usage-7d-performance.html
test -s /tmp/codex-usage-7d-performance.html
```

Expected: the largest file retains the accepted parser-equivalent behavior, and the seven-day report completes with a nonempty HTML file. Record aggregate timings only.

- [ ] **Step 3: Remove private temporary evidence and rerun the complete suite**

Run:

```bash
rm -rf /tmp/codex-usage-parser-baseline.json /tmp/codex-usage-parser-fixtures /tmp/codex-usage-7d-performance.html
uv run pytest -q
```

Expected: temporary evidence is absent and the suite passes.

- [ ] **Step 4: Continue with original Task 4 release preparation**

Execute original Task 4, `Prepare Preview Version 0.1.42`, from its RED release-contract tests through commit `chore: prepare 0.1.42 performance release`. Keep `preview: true`, set every package version to `0.1.42`, date both changelogs `2026-07-31`, and describe complete-file parallel cache refresh without claiming range pruning or append checkpoints.

- [ ] **Step 5: Continue with original Task 5 verification and publication**

Execute original Task 5, `Full Verification, Merge, Publish, and Stop Before Stable`. Both native jobs must include the new packaged parallel-cache smoke. Stop after Marketplace preview `0.1.42`; do not remove Preview or create `v1.0.0` before hands-on packaged validation on macOS Apple Silicon and Windows x64.

## Plan Completion Gate

The addendum is complete only when:

- serial and process-parallel complete-file records are exactly equal before unchanged parent finalization;
- usage and transition request/result contracts pass pickle round trips under spawn-compatible tests;
- worker count is deterministically bounded at four and serial fallback preserves exact results;
- SQLite access, including `state_5.sqlite`, occurs only in the parent;
- old successful rows survive worker and transaction failures until a complete replacement commits;
- interruption after one eight-file batch makes those eight generations reusable on the next load;
- file growth remains invalidated by the next size/mtime inventory;
- completion order cannot change cache records, observations, inferred transitions, or digests;
- schema versions and columns remain unchanged and no range-pruning or append-checkpoint state exists;
- every addendum-created or modified Python source/test file is below 500 lines;
- source tests, the complete suite, and aggregate cold/warm acceptance pass;
- frozen parallel-cache smoke passes in both the macOS arm64 and Windows x64 package workflows without recursive spawn or serial-fallback warning;
- ADR 0019 records the durable concurrency and recovery contract; and
- control returns to original Task 3 before `0.1.42` release preparation and publication.
