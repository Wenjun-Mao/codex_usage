# Parallel Usage Cache Refresh Addendum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cold and invalidated usage-cache refreshes complete reliably with bounded whole-file process workers and recoverable parent-only cache commits while preserving exact usage, transition, aggregation, and report semantics.

**Architecture:** The parent discovers and orders files, owns every SQLite operation, verifies all repository paths through one global ordered cache, finalizes records, infers transitions, and commits fixed eight-file batches. Spawned workers perform read-only complete-file parsing or raw transition-candidate extraction and return pickle-safe results with PID/timing evidence; process infrastructure failure may switch to observable serial fallback, while ordinary per-file errors remain data results and never restart a completed batch.

**Tech Stack:** Python 3.13, `os.process_cpu_count()`, `concurrent.futures.ProcessPoolExecutor`, `multiprocessing.get_context("spawn")`, frozen dataclasses, tenacity, SQLite, pytest, uv, PyInstaller 6.16+, Bash, PowerShell, and GitHub Actions.

## Global Constraints

- This addendum starts after the measured failure in Task 3 of `docs/superpowers/plans/2026-07-31-usage-parser-performance-and-0-1-42-release.md`. Original Tasks 1-2 and commits `b08eebb` and `c9b8d0f` remain accepted; commit `1fbe7de` is the pre-parser-gate equivalence oracle.
- Preserve exact parser records, pricing, token deltas, fork replay handling, parent identity inheritance, subagent inclusion, aggregation, transition inference, terminal/JSON/CSV/HTML output, and Task Transfer behavior.
- Keep `CACHE_SCHEMA_VERSION = 3`, `PARSER_CACHE_VERSION = 2`, and `PROJECT_TRANSITION_CACHE_VERSION = 1`. Add no table, column, index, trigger, persisted worker field, or persisted generation field.
- Do not prune files by report range, session start, filesystem mtime, cached timestamps, or inferred upper bounds. Range filtering remains after complete cache load and transition application.
- Do not persist a byte offset, tail buffer, partial line, token baseline, parser state, in-progress row, or within-file checkpoint. Every selected file is parsed by the unchanged `parse_session_file(path: Path) -> list[UsageRecord]` from byte zero through EOF.
- All cache SQLite and `state_5.sqlite` opens, reads, writes, transactions, and commits occur in the parent process. Worker import graphs must not reach parent SQLite modules.
- Default process capacity is `min(task_count, 4, max(1, os.process_cpu_count() or 1))`. Tests may force `max_workers=1`; production callers omit the override.
- Process startup, submission, pickling, broken-pool, or result-transport infrastructure failure may switch the unresolved read-only batch to serial execution. It must set `used_serial_fallback=True`, retain the infrastructure error, and emit one observable warning.
- An ordinary usage parse error or exhausted transition JSONL read error is returned by that worker as `"{ExceptionType}: {message}"`. It does not trigger pool fallback, does not restart successful work, and follows the existing per-file retain-or-skip behavior.
- Parse requests are contiguous inventory-ordered groups of eight. Workers run before `BEGIN IMMEDIATE`; the parent validates a complete result group, applies whole-file replacements/errors, marks transitions dirty, and commits once. An exception rolls back only the current group.
- Old successful `usage_records` and `session_metadata` rows remain until a complete replacement is present and its parent transaction commits. A failed replacement leaves old rows reusable as fallback but keeps an error marker so the file retries.
- Worker completion order cannot affect cache records, summaries, errors, retained-missing state, raw candidates, verified observations, inferred transitions, aggregation rows, payloads, or rendered reports.
- Normal CLI stdout/stderr and payload schemas stay unchanged. An explicit suppressed `--parallel-audit PATH` test/release diagnostic may write aggregate worker evidence without paths, task IDs, project names, or event text.
- Source acceptance runs from an importable guarded file, never `python -` or stdin. It fails unless resolved worker count is greater than one, at least two child PIDs execute, observed worker spans overlap, the parent PID is absent, and no serial fallback occurs.
- Frozen targets are exactly macOS Apple Silicon (`darwin-arm64`) and Windows x64 (`win32-x64`). Native build scripts reject any other OS/process architecture before packaging.
- A local developer proves only the native package matching the current host. After merged code is pushed and before a release tag is created, a non-publishing manual workflow run must prove both native jobs. Tagging/publishing remains blocked until that run succeeds.
- Use the existing `tenacity` dependency for explicitly listed read-only retries with `reraise=True`. Do not retry an ambiguous SQLite commit; roll back and retry the file generation on the next load.
- Every Python source/test/script file created or modified by this addendum must remain below 500 lines. Split cache, transition, test-support, equivalence, and smoke responsibilities into the files listed below.
- No task commit may leave the branch broken. Before each commit run that task's focused suite, `tests/test_python_source_size.py`, and `uv run pytest -q`; commit only after all pass.
- Release remains Marketplace Preview version `0.1.42`, dated `2026-07-31`. Stable `1.0.0` remains blocked by hands-on packaged validation on both supported platforms.

---

## Root Cause And Revision Basis

The failed command stopped before range filtering, aggregation, transition scanning, or rendering. The measured inventory had 2,275 current files totaling about 69.65 GB, with zero reusable entries: 1,921 new, 346 error-marked, seven metadata-changed, and one moved. A representative 2.25 GB file parsed in 6.228 seconds, but the serial refresh still traversed every selected byte. One transaction surrounded the complete inventory loop, so interruption at 171 seconds rolled back every completed file.

Cached-row materialization, range filtering, aggregation, and rendering were small relative to traversal. Read-only prototypes over the four largest files improved usage parsing from 21.49 to 6.66 seconds and transition extraction from 9.65 to 3.12 seconds with four processes; four threads did not improve parsing. This aggregate evidence supports bounded whole-file processes and smaller complete-generation transactions. It does not support range pruning, schema changes, within-file append checkpoints, or semantic changes.

The architecture review identified four proof gaps in the first addendum: stdin is not importable under spawn; temporary baselines can disappear; verifying paths independently in workers breaks the existing shared verification cache; and parent monkeypatches do not enter spawned children. The revised contracts below close those gaps and make worker identity, overlap, fallback, architecture, SQLite isolation, oracle equivalence, and release ordering executable gates.

## Exact Interfaces

All interfaces below are top-level and fully typed. `Path`, `datetime`, frozen dataclasses, tuples, strings, integers, and booleans are pickle-safe. No request/result contains a connection, exception object, closure, callback, lock, generator, or mutable cache.

### Execution Types

```text
DEFAULT_MAX_WORKERS: Final[int] = 4
SERIAL_FALLBACK_WARNING: Final[str] = "process pool infrastructure failed; continuing serially"

WorkerSpan(pid: int, started_ns: int, finished_ns: int)

ParallelRunReport(
    resolved_worker_count: int,
    worker_spans: tuple[WorkerSpan, ...],
    used_serial_fallback: bool,
    infrastructure_error: str,
    file_error_count: int,
)
EMPTY_PARALLEL_RUN_REPORT: Final[ParallelRunReport]
ParallelRunReport.worker_pids -> tuple[int, ...]
ParallelRunReport.max_concurrency -> int
ParallelRunReport.actually_parallel(parent_pid: int) -> bool
ParallelRunReport.to_dict() -> dict[str, object]

resolve_worker_count(
    task_count: int,
    *,
    available_cpus: int | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> int

OrderedProcessMapper[RequestT, ResultT](
    worker: Callable[[RequestT], ResultT],
    *,
    task_count: int,
    max_workers: int = DEFAULT_MAX_WORKERS,
)
OrderedProcessMapper.worker_count -> int
OrderedProcessMapper.used_serial_fallback -> bool
OrderedProcessMapper.infrastructure_error -> str
OrderedProcessMapper.map_batch(requests: Sequence[RequestT]) -> list[ResultT]
OrderedProcessMapper.__enter__() -> Self
OrderedProcessMapper.__exit__(exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None
```

`resolve_worker_count` uses the explicit `available_cpus` test value when provided; otherwise it calls `os.process_cpu_count()` exactly once. It returns zero for zero tasks and rejects negative task counts or `max_workers < 1` with `ValueError`.

`WorkerSpan` validates `pid > 0` and `finished_ns >= started_ns`. `ParallelRunReport.worker_pids` is first-seen PID order with duplicates removed. `max_concurrency` performs a deterministic sweep over worker intervals, processing a finish before a start at an equal timestamp so touching spans are not counted as overlap. `actually_parallel(parent_pid)` requires resolved count greater than one, no fallback, two or more non-parent PIDs, and `max_concurrency >= 2`.

`EMPTY_PARALLEL_RUN_REPORT` is exactly `ParallelRunReport(0, (), False, "", 0)`. `OrderedProcessMapper` uses a persistent `ProcessPoolExecutor` with the spawn context. It catches only pool infrastructure failures: constructor/submission `OSError`/`RuntimeError`, `pickle.PicklingError`, and `BrokenProcessPool` raised while submitting or retrieving a result. A normal exception raised by a worker future propagates and is not relabeled as infrastructure. Expected per-file failures never raise from a future because worker wrappers return typed error results. The parent supplies `file_error_count` when assembling a report; the mapper does not infer application errors.

### Usage Worker Types

```text
UsageParseRequest(
    ordinal: int,
    file_key: str,
    path: Path,
    size_bytes: int,
    mtime_ns: int,
)

UsageParseResult(
    request: UsageParseRequest,
    records: tuple[UsageRecord, ...],
    error: str,
    span: WorkerSpan,
)

parse_usage_request(request: UsageParseRequest) -> UsageParseResult

refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
    max_workers: int | None = None,
) -> tuple[CacheStats, ParallelRunReport]

load_cached_session_data(
    session_dirs: list[Path],
    *,
    cache_dir: Path | None = None,
    auto_transitions: bool = True,
    max_workers: int | None = None,
) -> CachedSessionData
```

`UsageParseResult` rejects records plus error. The worker starts its span before read retry and finishes it in both success and error results. It retries `OSError` up to three attempts using `wait_exponential(multiplier=0.05, min=0.05, max=0.2)`, `stop_after_attempt(3)`, `retry_if_exception_type(OSError)`, and `reraise=True`; the exhausted exception becomes the existing formatted per-file error.

`CacheStats` remains field-for-field unchanged so serial/parallel stats compare exactly. `CachedSessionData` gains non-persisted `usage_run: ParallelRunReport` and `transition_run: ParallelRunReport` fields with an empty-report default; no existing output serializer consumes them.

### Transition Candidate And Parent Verification Types

```text
RawRepoPathCandidate(
    raw_path: str,
    timestamp: datetime,
    thread_id: str,
    source: str,
)

TransitionScanRequest(ordinal: int, path: Path)

TransitionScanResult(
    request: TransitionScanRequest,
    candidates: tuple[RawRepoPathCandidate, ...],
    error: str,
    span: WorkerSpan,
)

scan_transition_request(request: TransitionScanRequest) -> TransitionScanResult

VerificationCache = dict[str, tuple[str, str, str] | None]

collect_jsonl_repo_path_candidates(path: Path) -> list[RawRepoPathCandidate]

read_jsonl_repo_path_candidates_once(path: Path) -> list[RawRepoPathCandidate]

verify_repo_path_candidates(
    candidates: Sequence[RawRepoPathCandidate],
    *,
    verification_cache: VerificationCache,
) -> list[RepoPathObservation]

collect_state_repo_path_observations(
    session_dirs: list[Path],
    *,
    verification_cache: VerificationCache,
) -> list[RepoPathObservation]

collect_repo_path_observations(
    session_dirs: list[Path],
    session_files: list[Path],
) -> list[RepoPathObservation]

collect_repo_path_observations_with_report(
    session_dirs: list[Path],
    session_files: list[Path],
    *,
    max_workers: int | None = None,
) -> tuple[list[RepoPathObservation], ParallelRunReport]
```

Workers decode JSONL and extract ordered raw candidates only. They never call `Path.exists`, `Path.resolve`, `normalize_project_key`, Git config readers, or SQLite. `read_jsonl_repo_path_candidates_once` opens and completely reads one file while preserving the current `errors="ignore"`, line order, thread-ID updates, event selection, path order, and malformed-line skip behavior. `collect_jsonl_repo_path_candidates` is the tenacity-decorated wrapper with `retry=retry_if_exception_type((OSError, UnicodeDecodeError))`, `stop=stop_after_attempt(3)`, `wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2)`, and `reraise=True`. After retries are exhausted, `scan_transition_request` catches only `(OSError, UnicodeDecodeError)` and returns `TransitionScanResult(request, (), f"{type(error).__name__}: {error}", span)`; parent collection skips that file exactly as the current serial scanner does. Other exceptions propagate and do not trigger per-file tolerance or process-pool fallback.

The parent sorts complete scan results by request ordinal, preserving line/candidate order within each result. It creates one `VerificationCache`, verifies every JSONL candidate in that order, then passes the same cache object to fully typed `collect_state_repo_path_observations`. State rows retain current session-dir, query-row, field, and candidate order. One unchanged dedupe/sort runs after both sources. This preserves the current globally shared path-verification semantics across files and across JSONL/state evidence.

### Audit And Acceptance Types

```text
write_parallel_audit(
    path: Path,
    *,
    parent_pid: int,
    usage_run: ParallelRunReport,
    transition_run: ParallelRunReport,
) -> Path

require_actual_parallel(
    report: ParallelRunReport,
    *,
    parent_pid: int,
    label: str,
) -> None

validate_target_architecture(
    expected_target: Literal["darwin-arm64", "win32-x64"],
    *,
    sys_platform: str,
    machine: str,
) -> None

scripts.parallel_cache_acceptance.main(argv: list[str] | None = None) -> int
scripts.packaged_parallel_cache_smoke.main(argv: list[str] | None = None) -> int
scripts.parser_equivalence_check.main(argv: list[str] | None = None) -> int
```

Audit JSON version 1 has exactly `version`, `parent_pid`, `sys_platform`, `machine`, `usage_run`, and `transition_run`. Each run object has exactly `resolved_worker_count`, `worker_pids`, `max_concurrency`, `used_serial_fallback`, `infrastructure_error`, `span_count`, and `file_error_count`. It contains no source path, session/thread ID, project identity, timestamp, token count, or event content. `require_actual_parallel` raises `RuntimeError(f"{label}: actual process parallelism not observed")` unless `report.actually_parallel(parent_pid)` is true. `validate_target_architecture` applies the exact platform/machine sets in Task 6 and raises `RuntimeError` on mismatch. The explicit audit option does not alter normal stdout payloads.

## Transaction And No-Checkpoint Contract

The parent commits missing/reuse metadata in a short preflight transaction. It then builds parse requests in exact inventory order and passes contiguous groups of eight to one persistent mapper. No write transaction is open while a group executes. When all eight or the final smaller group return, the parent verifies request equality and unique ordinals, sorts defensively, begins `IMMEDIATE`, applies each complete success/error, marks transitions dirty, and commits. Validation, insertion, interruption, or commit-path failure rolls back that complete group; earlier groups stay committed.

A successful replacement deletes old child rows only after its full `tuple[UsageRecord, ...]` is in the parent transaction. A worker error updates the existing file's error/last-seen fields without deleting old child rows, or inserts only an errored file row when no prior success exists. Size/mtime persisted from the request make growth during or after parsing invalidate the next inventory.

This is not an incremental append checkpoint. Workers reopen at byte zero and persist no offset, partial line, token baseline, tail digest, or parser state. After interruption, a file has its old complete generation, a committed new complete generation, or an error retaining its old complete generation. Eight-file transactions change recovery granularity only.

## File Map

| Path | Planned responsibility |
| --- | --- |
| `src/codex_usage/parser.py` | Read only: unchanged parser/finalizer and usage semantics. |
| `src/codex_usage/session_inventory.py` | Read only: inventory generation and ordering authority. |
| `src/codex_usage/parallel/__init__.py` | Re-export fully typed public internal parallel contracts. |
| `src/codex_usage/parallel/execution.py` | Worker span/report, worker count, spawn mapper, infrastructure-only fallback. |
| `src/codex_usage/parallel/usage.py` | Pickle-safe usage request/result and retrying top-level worker. |
| `src/codex_usage/parallel/transitions.py` | Pickle-safe transition request/result and retrying raw-candidate worker. |
| `src/codex_usage/session_cache_models.py` | Cache dataclasses and non-persisted run reports. |
| `src/codex_usage/session_cache_schema.py` | Existing schema constants/SQL/rebuild/snapshot unchanged. |
| `src/codex_usage/session_cache_store.py` | Parent-only cache row replacement/error/load and transition persistence. |
| `src/codex_usage/session_cache_refresh.py` | Reuse classification, eight-file parse groups, parent transactions/stats/report. |
| `src/codex_usage/session_cache.py` | Under-500 public facade, connection owner, finalization, transition orchestration. |
| `src/codex_usage/project_transition_evidence.py` | Existing path extraction/verification/dedupe plus parent candidate verification. |
| `src/codex_usage/project_transition_candidates.py` | JSONL-only raw candidate extraction; no SQLite/path verification. |
| `src/codex_usage/project_transition_state.py` | Parent-only fully typed `state_5.sqlite` observations using supplied global cache. |
| `src/codex_usage/project_transition_collection.py` | Parallel candidate ordering, shared parent cache, state append, final dedupe/report. |
| `src/codex_usage/project_transitions.py` | Unchanged inference/application; re-export collection facade. |
| `src/codex_usage/parallel_audit.py` | Aggregate audit JSON validation and atomic write. |
| `src/codex_usage/cli.py` | Existing command/payload behavior plus suppressed explicit audit path. |
| `src/codex_usage/__main__.py` | Call `freeze_support()` before CLI import. |
| `scripts/parallel_cache_acceptance.py` | Importable guarded source cold/warm acceptance. |
| `scripts/packaged_parallel_cache_smoke.py` | Importable guarded frozen CLI/audit/architecture smoke. |
| `scripts/parser_equivalence_check.py` | Fresh bounded fixture capture and detached-package digest/compare tool. |
| `scripts/build-macos-arm64-exe.sh` | macOS/arm64 guard, PyInstaller, parallel and transfer smokes. |
| `scripts/build-windows-exe.ps1` | Windows/x64 process guard, PyInstaller, parallel and transfer smokes. |
| `tests/parallel_cache_test_support.py` | Shared deterministic cache/report corpus builder below 500 lines. |
| `tests/spawn_worker_test_support.py` | Importable child-local SQLite guards and overlap workers below 500 lines. |
| `tests/project_transition_serial_oracle.py` | Frozen copy of the current shared-cache serial collector used only as oracle. |
| `tests/parallel_transition_test_support.py` | Deterministic JSONL/state/repository corpus builder below 500 lines. |
| `tests/test_parallel_execution.py` | Worker-count, span, concurrency, fallback classification, pickle tests. |
| `tests/test_parallel_cache_recovery.py` | Batch atomicity/interruption/error/growth tests. |
| `tests/test_parallel_cache_equivalence.py` | Full stats/summary/error/missing/schema equivalence. |
| `tests/test_parallel_report_equivalence.py` | Aggregation/payload/HTML/range equivalence. |
| `tests/test_parallel_transition_equivalence.py` | Serial-oracle equality, global cache order, retry/error tests. |
| `tests/test_spawn_sqlite_isolation.py` | Real spawn child guard and static dependency scans. |
| `tests/test_parallel_acceptance_scripts.py` | Importability/guards/audit/PID/architecture tests. |
| `tests/test_parser_equivalence_tool.py` | Self-contained capture/digest/compare CLI tests below 500 lines. |

---

### Task 1: Bounded Spawn Runtime And Observable Fallback

**Files:**
- Create: `src/codex_usage/parallel/__init__.py`
- Create: `src/codex_usage/parallel/execution.py`
- Create: `tests/spawn_worker_test_support.py`
- Create: `tests/test_parallel_execution.py`

**Interfaces:**
- Produces all Execution Types exactly as declared above.
- Leaves application parsing, cache, transitions, CLI, and outputs unchanged.

- [ ] **Step 1: Write exact failing runtime tests**

`tests/spawn_worker_test_support.py` defines these importable top-level types/functions; use `Any` only for `SyncManager` proxy fields because their runtime proxy classes are private:

```python
@dataclass(frozen=True, slots=True)
class OverlapRequest:
    ordinal: int
    barrier: Any
    active: Any
    peak: Any
    lock: Any


@dataclass(frozen=True, slots=True)
class OverlapResult:
    ordinal: int
    span: WorkerSpan


def overlap_worker(request: OverlapRequest) -> OverlapResult:
    started = time.monotonic_ns()
    pid = os.getpid()
    with request.lock:
        request.active.value += 1
        request.peak.value = max(request.peak.value, request.active.value)
    request.barrier.wait(timeout=20)
    with request.lock:
        request.active.value -= 1
    return OverlapResult(
        ordinal=request.ordinal,
        span=WorkerSpan(pid=pid, started_ns=started, finished_ns=time.monotonic_ns()),
    )
```

`tests/test_parallel_execution.py` contains complete tests with no local worker callable:

```python
def test_resolve_worker_count_uses_process_cpu_count(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def process_cpu_count() -> int:
        nonlocal calls
        calls += 1
        return 64

    monkeypatch.setattr(os, "process_cpu_count", process_cpu_count)
    assert resolve_worker_count(0) == 0
    assert resolve_worker_count(1) == 1
    assert resolve_worker_count(100) == 4
    assert calls == 2
    assert resolve_worker_count(100, available_cpus=2) == 2
    assert calls == 2


def test_spawn_mapper_proves_two_overlapping_child_pids() -> None:
    parent_pid = os.getpid()
    with multiprocessing.Manager() as manager:
        barrier = manager.Barrier(2)
        active = manager.Value("i", 0)
        peak = manager.Value("i", 0)
        lock = manager.Lock()
        requests = [OverlapRequest(index, barrier, active, peak, lock) for index in range(2)]
        with OrderedProcessMapper(overlap_worker, task_count=2, max_workers=2) as mapper:
            results = mapper.map_batch(requests)
        peak_value = peak.value
    report = ParallelRunReport(
        resolved_worker_count=mapper.worker_count,
        worker_spans=tuple(result.span for result in results),
        used_serial_fallback=mapper.used_serial_fallback,
        infrastructure_error=mapper.infrastructure_error,
        file_error_count=0,
    )
    assert peak_value == 2
    assert report.worker_pids == tuple(result.span.pid for result in results)
    assert parent_pid not in report.worker_pids
    assert report.max_concurrency == 2
    assert report.actually_parallel(parent_pid) is True
```

The same test module defines the following top-level spawn-safe callables and executor double. Production exposes no test-only hook; tests replace the module-owned `ProcessPoolExecutor`/`as_completed` names.

```python
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from multiprocessing.context import BaseContext
from typing import ClassVar, Never


WORKER_CALLS: list[int] = []


def recording_worker(value: int) -> int:
    WORKER_CALLS.append(value)
    return value * 10


def value_error_worker(value: int) -> int:
    raise ValueError(f"bad worker value {value}")


def interrupt_worker(value: int) -> int:
    raise KeyboardInterrupt(value)


class StubExecutor:
    fail_on: ClassVar[int | None] = None

    def __init__(self, *, max_workers: int, mp_context: BaseContext) -> None:
        self.max_workers = max_workers
        self.mp_context = mp_context
        self.futures: list[Future[int]] = []
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(self, worker: Callable[[int], int], request: int) -> Future[int]:
        future: Future[int] = Future()
        if request == self.fail_on:
            future.set_exception(BrokenProcessPool(f"transport failed for {request}"))
        else:
            future.set_result(worker(request))
        self.futures.append(future)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


def reversed_completed(futures: Iterable[Future[int]]) -> Iterator[Future[int]]:
    return iter(reversed(list(futures)))


def raising_executor(*args: object, **kwargs: object) -> Never:
    raise OSError("spawn unavailable")


@pytest.fixture(autouse=True)
def reset_executor_double() -> Iterator[None]:
    WORKER_CALLS.clear()
    StubExecutor.fail_on = None
    yield
    WORKER_CALLS.clear()
    StubExecutor.fail_on = None
```

Add these exact bodies:

```python
def test_reverse_future_completion_keeps_request_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", StubExecutor)
    monkeypatch.setattr(execution_module, "as_completed", reversed_completed)
    with OrderedProcessMapper(recording_worker, task_count=3, max_workers=3) as mapper:
        assert mapper.map_batch([1, 2, 3]) == [10, 20, 30]
    assert mapper.used_serial_fallback is False


def test_constructor_oserror_falls_back_once_and_is_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", raising_executor)
    with pytest.warns(RuntimeWarning, match=re.escape(SERIAL_FALLBACK_WARNING)) as caught:
        with OrderedProcessMapper(recording_worker, task_count=2, max_workers=2) as mapper:
            assert mapper.map_batch([1, 2]) == [10, 20]
    assert len(caught) == 1
    assert mapper.used_serial_fallback is True
    assert mapper.infrastructure_error == "OSError: spawn unavailable"


def test_broken_pool_reruns_current_group_but_not_committed_group(monkeypatch: pytest.MonkeyPatch) -> None:
    StubExecutor.fail_on = 3
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", StubExecutor)
    with pytest.warns(RuntimeWarning, match=re.escape(SERIAL_FALLBACK_WARNING)) as caught:
        with OrderedProcessMapper(recording_worker, task_count=3, max_workers=2) as mapper:
            assert mapper.map_batch([1]) == [10]
            assert mapper.map_batch([2, 3]) == [20, 30]
    assert len(caught) == 1
    assert WORKER_CALLS == [1, 2, 2, 3]
    assert mapper.used_serial_fallback is True
    assert mapper.infrastructure_error == "BrokenProcessPool: transport failed for 3"


def test_worker_value_error_is_not_pool_fallback() -> None:
    with OrderedProcessMapper(value_error_worker, task_count=1, max_workers=1) as mapper:
        with pytest.raises(ValueError, match="bad worker value 7"):
            mapper.map_batch([7])
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_keyboard_interrupt_is_never_caught() -> None:
    with OrderedProcessMapper(interrupt_worker, task_count=1, max_workers=1) as mapper:
        with pytest.raises(KeyboardInterrupt):
            mapper.map_batch([7])
    assert mapper.used_serial_fallback is False


@pytest.mark.parametrize(("task_count", "max_workers"), [(-1, 1), (1, 0)])
def test_invalid_worker_counts_raise(task_count: int, max_workers: int) -> None:
    with pytest.raises(ValueError):
        resolve_worker_count(task_count, available_cpus=8, max_workers=max_workers)
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_parallel_execution.py -q`

Expected: import fails because `codex_usage.parallel.execution` does not exist.

- [ ] **Step 3: Implement exact runtime contracts**

Implement the declared types and validation. Use `as_completed` to fill a position-indexed list. Catch infrastructure errors only at executor construction/submission/result transport; ordinary future exceptions propagate. On infrastructure fallback, discard the current group's read-only values, close/cancel the pool, warn once, run that group serially, and remain serial for later groups. Never catch `BaseException`.

- [ ] **Step 4: Verify GREEN and branch integrity**

Run:

```bash
uv run pytest tests/test_parallel_execution.py tests/test_python_source_size.py -q
uv run pytest -q
```

Expected: PASS; real spawn observes two overlapping non-parent PIDs and all existing tests remain green.

- [ ] **Step 5: Commit**

```bash
git add src/codex_usage/parallel/__init__.py src/codex_usage/parallel/execution.py tests/spawn_worker_test_support.py tests/test_parallel_execution.py
git commit -m "feat: add observable process worker runtime"
```

### Task 2: Split Cache Ownership Without Behavioral Change

**Files:**
- Create: `src/codex_usage/session_cache_models.py`
- Create: `src/codex_usage/session_cache_schema.py`
- Create: `src/codex_usage/session_cache_store.py`
- Modify: `src/codex_usage/session_cache.py`
- Modify: `tests/test_session_cache.py`
- Modify: `tests/test_cli_transitions.py`
- Modify: `tests/test_python_source_size.py`

**Interfaces:**
- Preserves every existing import from `codex_usage.session_cache` through re-exports.
- Produces parent-only `replace_file_generation(connection: sqlite3.Connection, session_dirs: list[Path], entry: SessionFileInventoryEntry, records: tuple[UsageRecord, ...]) -> None` and `record_file_error(connection: sqlite3.Connection, session_dirs: list[Path], entry: SessionFileInventoryEntry, error: str) -> None`, neither of which commits.
- Makes `session_cache.py` and all new modules shorter than 500 lines.

- [ ] **Step 1: Add a deterministic RED size guard**

Remove `src/codex_usage/session_cache.py` from `LEGACY_OVERSIZED_FILES` and add:

```python
def test_session_cache_facade_stays_under_500_lines() -> None:
    path = REPOSITORY_ROOT / "src" / "codex_usage" / "session_cache.py"
    assert _line_count(path) < 500
```

Run: `uv run pytest tests/test_python_source_size.py tests/test_session_cache.py tests/test_cli_transitions.py -q`

Expected: only the direct facade-size test fails at the current 767 lines.

- [ ] **Step 2: Move existing code with SQL text unchanged**

Move cache dataclasses to models; schema constants/create/match/rebuild/snapshot/restore to schema; row replacement/error/load, summaries, dirty state, and atomic transition replacement/load to store. Preserve table statement strings and public re-exports exactly. Keep the connection open only in `session_cache.py`.

Update moved-private-helper monkeypatches to their owning modules. Do not yet parallelize. Add empty `usage_run`/`transition_run` fields only after Task 3 introduces the report into cache models.

- [ ] **Step 3: Verify branch integrity**

Run:

```bash
uv run pytest tests/test_session_cache.py tests/test_cli_transitions.py tests/test_sync_inventory.py tests/test_sync_selection_inventory_loading.py tests/test_python_source_size.py -q
uv run pytest -q
```

Expected: PASS; `git diff` shows moved behavior and no SQL/version edit.

- [ ] **Step 4: Commit**

```bash
git add src/codex_usage/session_cache.py src/codex_usage/session_cache_models.py src/codex_usage/session_cache_schema.py src/codex_usage/session_cache_store.py tests/test_session_cache.py tests/test_cli_transitions.py tests/test_python_source_size.py
git commit -m "refactor: separate usage cache ownership"
```

### Task 3: Parallel Whole-File Parse And Eight-File Parent Commits

**Files:**
- Create: `src/codex_usage/parallel/usage.py`
- Create: `src/codex_usage/session_cache_refresh.py`
- Modify: `src/codex_usage/parallel/__init__.py`
- Modify: `src/codex_usage/session_cache_models.py`
- Modify: `src/codex_usage/session_cache.py`
- Create: `tests/parallel_cache_test_support.py`
- Create: `tests/test_parallel_cache_recovery.py`
- Modify: `tests/test_session_cache.py`
- Modify: `tests/test_sync_runner_validation.py`

**Interfaces:**
- Produces all Usage Worker Types and transaction behavior declared above.
- Keeps `CacheStats` exact and adds only non-persisted run reports to `CachedSessionData`.

- [ ] **Step 1: Create importable deterministic corpus support**

`tests/parallel_cache_test_support.py` defines a frozen `UsageCorpus` with fully typed `sessions: Path`, `ordered_paths: tuple[Path, ...]`, `corrupt_path: Path`, `missing_path: Path`, and `recent_old_metadata_path: Path`. `write_usage_corpus(root: Path) -> UsageCorpus` writes nine files in sortable names: normal, parent, structured subagent, fork replay, Unicode-escaped event names, empty valid, future-missing, old-start/old-mtime with a current token event, and invalid UTF-8. Use fixed token totals and current UTC only for the recent event; return every path explicitly. The module also provides:

```text
load_serial(corpus: UsageCorpus, cache_dir: Path, *, auto_transitions: bool) -> CachedSessionData
load_parallel(corpus: UsageCorpus, cache_dir: Path, *, auto_transitions: bool) -> CachedSessionData
```

`load_serial` calls `load_cached_session_data(..., max_workers=1)`; `load_parallel` calls `max_workers=4`. No pytest fixture or closure crosses spawn.

The same module defines every recovery-test dependency explicitly:

```text
GenerationSnapshot = tuple[tuple[object, ...], ...]

write_valid_usage_set(root: Path, *, count: int) -> tuple[Path, tuple[Path, ...]]
append_cumulative_token_total(path: Path, *, total_tokens: int, timestamp: str) -> None
complete_generation_snapshot(cache_dir: Path) -> GenerationSnapshot

SerialTestMapper[RequestT, ResultT](worker: Callable[[RequestT], ResultT], *, task_count: int, max_workers: int)
SerialTestMapper.worker_count -> int
SerialTestMapper.used_serial_fallback -> bool
SerialTestMapper.infrastructure_error -> str
SerialTestMapper.map_batch(requests: Sequence[RequestT]) -> list[ResultT]
SerialTestMapper.__enter__() -> Self
SerialTestMapper.__exit__(exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None

ReverseResultMapper[RequestT, ResultT](SerialTestMapper[RequestT, ResultT])
InterruptAfterFirstBatchMapper[RequestT, ResultT](SerialTestMapper[RequestT, ResultT])
```

`write_valid_usage_set` rejects counts below one and writes sortable `000.jsonl` through `{count - 1:03d}.jsonl`, each with one `session_meta` and one cumulative `token_count` at a fixed UTC timestamp; file `i` totals `100 + i`. `append_cumulative_token_total` appends one valid event. `complete_generation_snapshot` reads the cache read-only and returns ordered tuples from `files` excluding `last_seen_at`, followed by all ordered `usage_records` and `session_metadata`; it therefore compares every persisted complete-generation field without a volatile observation timestamp. `SerialTestMapper` executes the supplied top-level worker in request order, reports the resolved deterministic worker count but no fallback, and implements the declared context manager. `ReverseResultMapper.map_batch` returns those results reversed. `InterruptAfterFirstBatchMapper.map_batch` delegates its first call and raises `KeyboardInterrupt("after first committed batch")` before evaluating its second call. These doubles remain test-only and below 500 lines.

- [ ] **Step 2: Write exact failing worker and recovery tests**

`tests/test_parallel_cache_recovery.py` includes full-body tests that construct their corpus locally:

```python
def test_usage_request_and_result_are_pickle_safe(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    path = corpus.ordered_paths[0]
    stat = path.stat()
    request = UsageParseRequest(0, path.stem, path, stat.st_size, stat.st_mtime_ns)
    assert pickle.loads(pickle.dumps(request)) == request
    result = parse_usage_request(request)
    assert result.error == ""
    assert result.records
    assert result.span.pid == os.getpid()
    assert pickle.loads(pickle.dumps(result)) == result


def test_usage_file_error_is_data_not_pool_fallback(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    path = corpus.corrupt_path
    stat = path.stat()
    request = UsageParseRequest(0, path.stem, path, stat.st_size, stat.st_mtime_ns)
    with OrderedProcessMapper(parse_usage_request, task_count=1, max_workers=1) as mapper:
        result = mapper.map_batch([request])[0]
    assert result.records == ()
    assert result.error.startswith("UnicodeDecodeError: ")
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""
```

Add these full bodies. Every monkeypatch affects parent-owned orchestration and every load under a monkeypatch is forced through an importable serial test mapper; no test expects a patch to enter a spawned child.

```python
def test_reverse_completion_preserves_inventory_record_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, paths = write_valid_usage_set(tmp_path / "codex", count=9)
    monkeypatch.setattr(refresh_module, "OrderedProcessMapper", ReverseResultMapper)
    data = load_cached_session_data(
        [sessions], cache_dir=tmp_path / "cache", auto_transitions=False, max_workers=4
    )
    assert data.files == list(paths)
    assert [record.file_path for record in data.records] == list(paths)
    assert [record.usage.total_tokens for record in data.records] == list(range(100, 109))


def test_worker_error_retains_old_complete_rows_and_retries(tmp_path: Path) -> None:
    sessions, (path,) = write_valid_usage_set(tmp_path / "codex", count=1)
    cache_dir = tmp_path / "cache"
    initial = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    old_snapshot = complete_generation_snapshot(cache_dir)
    path.write_bytes(b"\xff\xfe")

    failed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert failed.stats.file_errors == 1
    assert failed.stats.files_parsed == 1
    assert failed.records == initial.records
    assert failed.file_errors[str(path)].startswith("UnicodeDecodeError: ")
    assert complete_generation_snapshot(cache_dir) != old_snapshot
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute("select count(*) from usage_records").fetchone() == (1,)
        assert connection.execute("select count(*) from session_metadata").fetchone() == (1,)

    write_valid_usage_set(tmp_path / "replacement", count=1)[1][0].replace(path)
    recovered = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert recovered.stats.files_parsed == 1
    assert recovered.stats.file_errors == 0
    assert recovered.file_errors == {}
    assert [record.usage.total_tokens for record in recovered.records] == [100]


def test_insert_failure_rolls_back_all_eight_replacements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, paths = write_valid_usage_set(tmp_path / "codex", count=8)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1)
    before = complete_generation_snapshot(cache_dir)
    for index, path in enumerate(paths):
        append_cumulative_token_total(
            path, total_tokens=200 + index, timestamp=f"2026-07-31T12:{index:02d}:00Z"
        )

    calls = 0
    original = refresh_module.replace_file_generation

    def fail_second_replacement(
        connection: sqlite3.Connection,
        session_dirs: list[Path],
        entry: SessionFileInventoryEntry,
        records: tuple[UsageRecord, ...],
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError("injected second replacement failure")
        original(connection, session_dirs, entry, records)

    monkeypatch.setattr(refresh_module, "replace_file_generation", fail_second_replacement)
    with pytest.raises(sqlite3.IntegrityError, match="injected second replacement failure"):
        load_cached_session_data(
            [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
        )
    assert calls == 2
    assert complete_generation_snapshot(cache_dir) == before


def test_interrupt_after_first_group_reuses_exactly_eight_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, paths = write_valid_usage_set(tmp_path / "codex", count=9)
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(refresh_module, "OrderedProcessMapper", InterruptAfterFirstBatchMapper)
    with pytest.raises(KeyboardInterrupt, match="after first committed batch"):
        load_cached_session_data(
            [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=4
        )
    monkeypatch.undo()

    resumed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert resumed.stats.files_reused == 8
    assert resumed.stats.files_parsed == 1
    assert [record.file_path for record in resumed.records] == list(paths)
    assert sum(record.usage.total_tokens for record in resumed.records) == sum(range(100, 109))
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select count(*) from (select file_key, record_index from usage_records "
            "group by file_key, record_index having count(*) = 1)"
        ).fetchone() == (9,)
        assert tuple(connection.execute(
            "select key, value from schema_meta where key in "
            "('schema_version','parser_version','project_transition_version') order by key"
        )) == (
            ("parser_version", "2"),
            ("project_transition_version", "1"),
            ("schema_version", "3"),
        )


def test_growth_after_parse_forces_next_load_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, (path,) = write_valid_usage_set(tmp_path / "codex", count=1)
    cache_dir = tmp_path / "cache"
    original = refresh_module.parse_usage_request
    grew = False

    def parse_then_grow(request: UsageParseRequest) -> UsageParseResult:
        nonlocal grew
        result = original(request)
        if not grew:
            append_cumulative_token_total(
                path, total_tokens=160, timestamp="2026-07-31T12:30:00Z"
            )
            grew = True
        return result

    monkeypatch.setattr(refresh_module, "parse_usage_request", parse_then_grow)
    first = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    monkeypatch.undo()
    second = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert [record.usage.total_tokens for record in first.records] == [100]
    assert second.stats.files_parsed == 1
    assert [record.usage.total_tokens for record in second.records] == [100, 60]
```

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_parallel_cache_recovery.py -q`

Expected: import fails because usage worker/refresh modules do not exist.

- [ ] **Step 4: Implement worker and parent refresh**

Implement the exact retry/result/span contract. In `refresh_files`, commit missing/reuse preflight separately, build inventory-ordinal requests, reuse one mapper, process `itertools.batched(requests, 8)`, validate all result requests before `BEGIN IMMEDIATE`, and commit/rollback as specified. Assemble one `ParallelRunReport` from all spans and mapper flags. Per-file errors count in `CacheStats.files_parsed`/`file_errors` and never trigger mapper fallback.

Add keyword-only `max_workers` to `load_cached_session_data`. Existing monkeypatch-based cache tests must pass `max_workers=1` and patch `codex_usage.parallel.usage.parse_session_file` or the new owning parent helper. Explicitly update every existing test that expects an in-process monkeypatch; do not rely on fork inheritance.

- [ ] **Step 5: Verify branch integrity**

Run:

```bash
uv run pytest tests/test_parallel_execution.py tests/test_parallel_cache_recovery.py tests/test_session_cache.py tests/test_parser_aggregation.py tests/test_parser_relevance_gate.py tests/test_session_provenance.py tests/test_token_usage.py tests/test_pricing.py tests/test_python_source_size.py -q
uv run pytest -q
```

Expected: PASS with exact usage semantics and all changed files below 500 lines.

- [ ] **Step 6: Commit**

```bash
git add src/codex_usage/parallel/__init__.py src/codex_usage/parallel/usage.py src/codex_usage/session_cache.py src/codex_usage/session_cache_models.py src/codex_usage/session_cache_refresh.py tests/parallel_cache_test_support.py tests/test_parallel_cache_recovery.py tests/test_session_cache.py tests/test_sync_runner_validation.py
git commit -m "perf: commit parallel whole-file cache groups"
```

### Task 4: Raw Transition Workers And One Parent Verification Cache

**Files:**
- Create: `src/codex_usage/project_transition_candidates.py`
- Create: `src/codex_usage/project_transition_state.py`
- Create: `src/codex_usage/project_transition_collection.py`
- Create: `src/codex_usage/parallel/transitions.py`
- Modify: `src/codex_usage/project_transition_evidence.py`
- Modify: `src/codex_usage/project_transitions.py`
- Modify: `src/codex_usage/session_cache.py`
- Modify: `src/codex_usage/parallel/__init__.py`
- Create: `tests/project_transition_serial_oracle.py`
- Create: `tests/parallel_transition_test_support.py`
- Create: `tests/test_parallel_transition_equivalence.py`
- Create: `tests/test_spawn_sqlite_isolation.py`
- Modify: `tests/spawn_worker_test_support.py`
- Modify: `tests/test_project_transition_evidence.py`
- Modify: `tests/test_cli_transitions.py`

**Interfaces:**
- Produces all Transition Candidate And Parent Verification Types exactly as declared.
- Preserves the current serial collector as an independent test oracle with one shared verification cache.
- Proves worker SQLite isolation dynamically inside spawned children and statically by import/dependency scan.

- [ ] **Step 1: Freeze the untouched serial oracle before production refactor**

Copy `collect_repo_path_observations`, its JSONL loop, state loop, shared `_VerificationCache`, cached verification helper, and final dedupe ordering directly from `git show 1fbe7de:src/codex_usage/project_transition_evidence.py` into `tests/project_transition_serial_oracle.py`. Change imports only so the oracle calls the public extraction/normalization types that were already present at `1fbe7de`. Add a source header `Frozen from 1fbe7de; do not refactor with production collectors` and a test asserting the oracle passes one cache object through JSONL and state collection. Do not modify this oracle in later steps and never build expected observations with a newly extracted production helper.

Create `tests/parallel_transition_test_support.py` with no pytest fixtures and these exact contracts:

```text
TransitionCorpus(
    session_dirs: tuple[Path, ...],
    session_files: tuple[Path, ...],
    repeated_repo: Path,
)

write_transition_corpus(root: Path, *, repeat_same_path: bool = False) -> TransitionCorpus
```

The builder creates two repositories with literal `.git/config` origin URLs `https://github.com/example/alpha.git` and `https://github.com/example/beta.git`; two ordered JSONLs containing session metadata, valid function-call workdirs, a malformed JSON line, ignored user/output paths, and invalid UTF-8 bytes; and `<codex-home>/state_5.sqlite` with the current minimal `threads(id, cwd, updated_at)` schema. Timestamps and thread IDs are fixed. With `repeat_same_path=True`, the alpha path appears in both JSONLs and the state row, so a single shared cache must resolve it once. The returned tuples are already in serial inventory order.

- [ ] **Step 2: Write exact failing candidate/oracle/retry tests**

`tests/test_parallel_transition_equivalence.py` writes its files and repositories inside each test; no undefined fixture is referenced. Include these complete bodies:

```python
def test_parallel_collection_equals_frozen_serial_oracle(tmp_path: Path) -> None:
    corpus = write_transition_corpus(tmp_path)
    session_dirs = list(corpus.session_dirs)
    session_files = list(corpus.session_files)
    expected = serial_oracle.collect_repo_path_observations(session_dirs, session_files)
    actual, report = collect_repo_path_observations_with_report(
        session_dirs,
        session_files,
        max_workers=2,
    )
    assert actual == expected
    assert report.resolved_worker_count == 2
    assert report.used_serial_fallback is False


def test_parent_uses_one_cache_across_jsonl_files_and_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = write_transition_corpus(tmp_path, repeat_same_path=True)
    session_dirs = list(corpus.session_dirs)
    session_files = list(corpus.session_files)
    seen_cache_ids: list[int] = []
    resolutions: list[str] = []
    original_verify = evidence_module.verify_repo_path_candidates
    original_state = state_module.collect_state_repo_path_observations
    original_resolve = evidence_module.verified_repo_observation_from_path

    def track_verify(candidates: Sequence[RawRepoPathCandidate], *, verification_cache: VerificationCache) -> list[RepoPathObservation]:
        seen_cache_ids.append(id(verification_cache))
        return original_verify(candidates, verification_cache=verification_cache)

    def track_state(session_dirs: list[Path], *, verification_cache: VerificationCache) -> list[RepoPathObservation]:
        seen_cache_ids.append(id(verification_cache))
        return original_state(session_dirs, verification_cache=verification_cache)

    def track_resolution(
        raw_path: str | Path,
        timestamp: datetime,
        thread_id: str,
        source: str,
    ) -> RepoPathObservation | None:
        resolutions.append(str(raw_path))
        return original_resolve(raw_path, timestamp, thread_id, source)

    monkeypatch.setattr(evidence_module, "verify_repo_path_candidates", track_verify)
    monkeypatch.setattr(state_module, "collect_state_repo_path_observations", track_state)
    monkeypatch.setattr(evidence_module, "verified_repo_observation_from_path", track_resolution)
    collect_repo_path_observations_with_report(session_dirs, session_files, max_workers=1)
    assert len(seen_cache_ids) == len(session_files) + 1
    assert len(set(seen_cache_ids)) == 1
    assert resolutions.count(str(corpus.repeated_repo)) == 1


def test_transition_request_result_pickle_and_reverse_order_match_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = write_transition_corpus(tmp_path)
    requests = tuple(
        TransitionScanRequest(ordinal, path)
        for ordinal, path in enumerate(corpus.session_files)
    )
    assert pickle.loads(pickle.dumps(requests)) == requests
    direct = scan_transition_request(requests[0])
    assert pickle.loads(pickle.dumps(direct)) == direct

    expected = serial_oracle.collect_repo_path_observations(
        list(corpus.session_dirs), list(corpus.session_files)
    )
    monkeypatch.setattr(collection_module, "OrderedProcessMapper", ReverseResultMapper)
    actual, report = collect_repo_path_observations_with_report(
        list(corpus.session_dirs), list(corpus.session_files), max_workers=2
    )
    assert actual == expected
    assert report.used_serial_fallback is False
    assert report.file_error_count == 0


@pytest.mark.parametrize(
    "failure",
    [
        OSError("transition read unavailable"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["oserror", "unicode"],
)
def test_transition_read_exhaustion_is_three_attempt_error_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: OSError | UnicodeDecodeError,
) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    calls = 0

    def fail_once(_path: Path) -> list[RawRepoPathCandidate]:
        nonlocal calls
        calls += 1
        raise failure

    monkeypatch.setattr(candidate_module, "read_jsonl_repo_path_candidates_once", fail_once)
    request = TransitionScanRequest(0, path)
    with OrderedProcessMapper(scan_transition_request, task_count=1, max_workers=1) as mapper:
        result = mapper.map_batch([request])[0]
    assert calls == 3
    assert result.request == request
    assert result.candidates == ()
    assert result.error == f"{type(failure).__name__}: {failure}"
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_transition_non_io_error_propagates_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    def fail_once(_path: Path) -> list[RawRepoPathCandidate]:
        raise ValueError("candidate contract violated")

    monkeypatch.setattr(candidate_module, "read_jsonl_repo_path_candidates_once", fail_once)
    with OrderedProcessMapper(scan_transition_request, task_count=1, max_workers=1) as mapper:
        with pytest.raises(ValueError, match="candidate contract violated"):
            mapper.map_batch([TransitionScanRequest(0, path)])
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""
```

- [ ] **Step 3: Add child-local SQLite guards and static scans**

Extend `tests/spawn_worker_test_support.py` with these exact top-level child callables. The assignment occurs after spawn import inside each child, so it does not rely on a parent monkeypatch:

```python
def reject_sqlite_connect(*args: object, **kwargs: object) -> Never:
    raise AssertionError("worker attempted SQLite")


def guarded_usage_worker(request: UsageParseRequest) -> UsageParseResult:
    original = sqlite3.connect
    sqlite3.connect = reject_sqlite_connect
    try:
        return parse_usage_request(request)
    finally:
        sqlite3.connect = original


def guarded_transition_worker(request: TransitionScanRequest) -> TransitionScanResult:
    original = sqlite3.connect
    sqlite3.connect = reject_sqlite_connect
    try:
        return scan_transition_request(request)
    finally:
        sqlite3.connect = original
```

`tests/test_spawn_sqlite_isolation.py` defines `local_import_closure(entry_modules: tuple[str, ...]) -> dict[str, tuple[str, ...]]` using `ast.Import`/`ast.ImportFrom` and package paths below `src/codex_usage`; it recursively visits every local import from the worker entry modules, rejects `ast.Call` to `__import__` or `importlib.import_module`, and returns sorted imports per module. Add these complete tests:

```python
def test_spawned_usage_and_transition_workers_cannot_open_sqlite(tmp_path: Path) -> None:
    usage_corpus = write_usage_corpus(tmp_path / "usage")
    usage_requests = []
    for ordinal, path in enumerate(usage_corpus.ordered_paths[:2]):
        stat = path.stat()
        usage_requests.append(
            UsageParseRequest(ordinal, path.stem, path, stat.st_size, stat.st_mtime_ns)
        )
    transition_corpus = write_transition_corpus(tmp_path / "transition")
    transition_requests = [
        TransitionScanRequest(ordinal, path)
        for ordinal, path in enumerate(transition_corpus.session_files)
    ]

    with OrderedProcessMapper(guarded_usage_worker, task_count=2, max_workers=2) as usage_mapper:
        usage_results = usage_mapper.map_batch(usage_requests)
    with OrderedProcessMapper(
        guarded_transition_worker, task_count=2, max_workers=2
    ) as transition_mapper:
        transition_results = transition_mapper.map_batch(transition_requests)

    parent_pid = os.getpid()
    assert all(result.span.pid != parent_pid and result.error == "" for result in usage_results)
    assert all(result.records for result in usage_results)
    assert all(result.span.pid != parent_pid and result.error == "" for result in transition_results)
    assert all(result.candidates for result in transition_results)
    assert usage_mapper.used_serial_fallback is False
    assert transition_mapper.used_serial_fallback is False


def test_worker_import_closure_has_no_sqlite_or_parent_store_dependency() -> None:
    closure = local_import_closure(
        (
            "codex_usage.parallel.usage",
            "codex_usage.parallel.transitions",
            "codex_usage.project_transition_candidates",
        )
    )
    forbidden = {
        "sqlite3",
        "codex_usage.project_transition_state",
        "codex_usage.project_transition_collection",
        "codex_usage.session_cache",
        "codex_usage.session_cache_schema",
        "codex_usage.session_cache_store",
        "codex_usage.session_cache_refresh",
    }
    imported = {name for names in closure.values() for name in names}
    assert imported.isdisjoint(forbidden)
    assert "codex_usage.project_transition_state" not in closure
    collection_imports = local_import_closure(("codex_usage.project_transition_collection",))[
        "codex_usage.project_transition_collection"
    ]
    assert "codex_usage.project_transition_state" in collection_imports
```

- [ ] **Step 4: Verify RED**

Run:

```bash
uv run pytest tests/test_parallel_transition_equivalence.py tests/test_spawn_sqlite_isolation.py -q
```

Expected: imports fail because candidate/state/collection/transition-worker modules do not exist.

- [ ] **Step 5: Implement raw candidates, parent verification, and reports**

Move JSONL decoding/text selection into the candidate module and return `RawRepoPathCandidate` in line/path order. Apply the exact three-attempt retry in the worker. Keep path existence/resolve/Git normalization and dedupe in evidence. Move `state_5.sqlite` reads into the fully typed state function and require the caller's cache. The state module and collection module import their owning modules, not copied function aliases, so parent monkeypatch tests observe the calls. Build collection results in request order, call `evidence_module.verify_repo_path_candidates` once per ordered JSONL result with one parent cache, pass that same cache to `state_module.collect_state_repo_path_observations`, then use the unchanged dedupe sort. Cache refresh consumes the report; public two-argument collection returns observations only.

Update existing transition monkeypatch tests to use private collection with `max_workers=1` and patch owning modules. Do not expect parent monkeypatches to affect real spawned workers.

- [ ] **Step 6: Verify branch integrity**

Run:

```bash
uv run pytest tests/test_parallel_transition_equivalence.py tests/test_spawn_sqlite_isolation.py tests/test_project_transition_evidence.py tests/test_project_transition_detection.py tests/test_project_transitions.py tests/test_cli_transitions.py tests/test_session_cache.py tests/test_python_source_size.py -q
uv run pytest -q
```

Expected: PASS; oracle equality is exact, one parent cache ID is observed, and child-local guards see no SQLite call.

- [ ] **Step 7: Commit**

```bash
git add src/codex_usage/project_transition_candidates.py src/codex_usage/project_transition_state.py src/codex_usage/project_transition_collection.py src/codex_usage/project_transition_evidence.py src/codex_usage/project_transitions.py src/codex_usage/parallel/__init__.py src/codex_usage/parallel/transitions.py src/codex_usage/session_cache.py tests/project_transition_serial_oracle.py tests/parallel_transition_test_support.py tests/spawn_worker_test_support.py tests/test_parallel_transition_equivalence.py tests/test_spawn_sqlite_isolation.py tests/test_project_transition_evidence.py tests/test_cli_transitions.py
git commit -m "perf: extract transition evidence in worker processes"
```

### Task 5: Full Serial/Parallel Semantic And Schema Equivalence

**Files:**
- Create: `tests/test_parallel_cache_equivalence.py`
- Create: `tests/test_parallel_report_equivalence.py`
- Modify: `tests/parallel_cache_test_support.py`

**Interfaces:**
- Verifies full returned cache state, exact normalized schema text/version, aggregation/payload/HTML equivalence, and no range pruning.
- Adds no production behavior.

- [ ] **Step 1: Add an exact schema snapshot helper**

In test support define:

```python
def normalized_schema(connection: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(
        "select name, sql from sqlite_master "
        "where type = 'table' and name not like 'sqlite_%' order by name"
    ).fetchall()
    return tuple((str(name), " ".join(str(sql).split())) for name, sql in rows)
```

Define the expected constants literally; do not derive expected SQL from production at test runtime:

```python
EXPECTED_SCHEMA_META = (
    ("parser_version", "2"),
    ("project_transition_version", "1"),
    ("schema_version", "3"),
)
EXPECTED_NORMALIZED_SCHEMA = (
    ("files", "create table files ( file_key text primary key, path text not null, "
     "session_dir text not null, storage_state text not null, size_bytes integer not null, "
     "mtime_ns integer not null, parsed_at text not null, last_seen_at text not null, "
     "missing_since text, is_missing integer not null, session_id text, error text )"),
    ("project_transitions", "create table project_transitions ( source_key text not null, "
     "source_label text not null, target_key text not null, target_label text not null, "
     "effective_from text not null, confidence integer not null, evidence_json text not null, "
     "thread_ids_json text not null )"),
    ("schema_meta", "create table schema_meta (key text primary key, value text not null)"),
    ("session_metadata", "create table session_metadata ( file_key text primary key, "
     "file_path text not null, session_dir text not null, storage_state text not null, "
     "is_missing integer not null, session_id text not null, cwd text, project_key text, "
     "project_label text, project_aliases_json text not null, git_repository_url text, "
     "git_branch text, memory_mode text, has_base_instructions integer not null, "
     "session_bytes integer not null, estimated_sync_bytes integer not null )"),
    ("usage_records", "create table usage_records ( file_key text not null, file_path text not null, "
     "record_index integer not null, timestamp text not null, session_id text not null, "
     "turn_id text, model text not null, effort text, collaboration_mode text, "
     "project_key text not null, project_label text not null, project_aliases_json text not null, "
     "cwd text, git_repository_url text, git_branch text, parent_thread_id text, "
     "input_tokens integer not null, cached_input_tokens integer not null, "
     "cache_write_input_tokens integer not null default 0, output_tokens integer not null, "
     "reasoning_output_tokens integer not null, total_tokens integer not null, "
     "primary key (file_key, record_index) )"),
)
```

- [ ] **Step 2: Write executable full-state tests**

`tests/test_parallel_cache_equivalence.py` contains complete bodies:

```python
def test_serial_and_parallel_cache_state_are_exactly_equal(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    serial_cache = tmp_path / "serial-cache"
    parallel_cache = tmp_path / "parallel-cache"
    serial = load_serial(corpus, serial_cache, auto_transitions=False)
    parallel = load_parallel(corpus, parallel_cache, auto_transitions=False)

    assert parallel.stats == serial.stats
    assert parallel.files == serial.files
    assert parallel.records == serial.records
    assert parallel.file_summaries == serial.file_summaries
    assert parallel.file_errors == serial.file_errors
    assert parallel.retained_missing_files == serial.retained_missing_files
    assert parallel.project_transitions == serial.project_transitions == []
    assert parallel.usage_run.resolved_worker_count > 1
    assert parallel.usage_run.used_serial_fallback is False

    for cache_dir in (serial_cache, parallel_cache):
        with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
            assert normalized_schema(connection) == EXPECTED_NORMALIZED_SCHEMA
            metadata = tuple(connection.execute(
                "select key, value from schema_meta "
                "where key in ('schema_version','parser_version','project_transition_version') "
                "order by key"
            ))
            assert metadata == EXPECTED_SCHEMA_META


def test_serial_and_parallel_errors_and_retained_missing_are_equal(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    serial_cache = tmp_path / "serial-cache"
    parallel_cache = tmp_path / "parallel-cache"
    load_serial(corpus, serial_cache, auto_transitions=False)
    load_parallel(corpus, parallel_cache, auto_transitions=False)
    corpus.missing_path.unlink()

    serial = load_serial(corpus, serial_cache, auto_transitions=False)
    parallel = load_parallel(corpus, parallel_cache, auto_transitions=False)
    assert parallel.stats == serial.stats
    assert parallel.records == serial.records
    assert parallel.file_summaries == serial.file_summaries
    assert parallel.file_errors == serial.file_errors
    assert parallel.retained_missing_files == serial.retained_missing_files == [corpus.missing_path]
```

Add `attach_transition_evidence(corpus: UsageCorpus) -> None` to test support. It appends fixed post-usage function-call evidence to one valid session, creates a target repository with origin `https://github.com/example/moved-project.git`, and creates one fixed `state_5.sqlite` thread row for that same target without changing any usage event. Then add this body, which derives expected observations only from the frozen oracle:

```python
def test_serial_and_parallel_transition_enabled_state_is_exactly_equal(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    attach_transition_evidence(corpus)
    expected_observations = serial_oracle.collect_repo_path_observations(
        [corpus.sessions], list(corpus.ordered_paths)
    )
    raw = load_serial(corpus, tmp_path / "raw-cache", auto_transitions=False)
    expected_transitions = infer_project_transitions(raw.records, expected_observations)
    assert expected_observations
    assert expected_transitions

    serial = load_serial(corpus, tmp_path / "serial-cache", auto_transitions=True)
    parallel = load_parallel(corpus, tmp_path / "parallel-cache", auto_transitions=True)
    actual_observations, transition_run = collect_repo_path_observations_with_report(
        [corpus.sessions], list(corpus.ordered_paths), max_workers=4
    )
    assert actual_observations == expected_observations
    assert serial.project_transitions == parallel.project_transitions == expected_transitions
    assert parallel.records == serial.records
    assert parallel.file_summaries == serial.file_summaries
    assert parallel.stats == serial.stats
    assert parallel.file_errors == serial.file_errors
    assert parallel.retained_missing_files == serial.retained_missing_files
    assert transition_run.resolved_worker_count > 1
    assert transition_run.used_serial_fallback is False
```

- [ ] **Step 3: Write executable aggregation, payload, report, and old-mtime tests**

`tests/test_parallel_report_equivalence.py` uses one fixed `generated_at` and output path per rendering pass:

```python
def test_serial_parallel_aggregation_payload_and_html_are_identical(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    serial = load_serial(corpus, tmp_path / "serial-cache", auto_transitions=True)
    parallel = load_parallel(corpus, tmp_path / "parallel-cache", auto_transitions=True)
    timezone = resolve_timezone("UTC")
    generated_at = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    serial_rows = {group: aggregate_records(serial.records, group, timezone) for group in GROUP_CHOICES}
    parallel_rows = {group: aggregate_records(parallel.records, group, timezone) for group in GROUP_CHOICES}
    assert parallel_rows == serial_rows
    assert summarize_records(parallel.records) == summarize_records(serial.records)

    serial_payload = summary_payload(
        rows=serial_rows["day"], total=summarize_records(serial.records),
        generated_at=generated_at, range_name="all", group_by="day",
        sessions_dirs=serial.session_dirs, files_scanned=len(serial.files),
        storage_roots=[str(path) for path in serial.session_dirs],
        files_archived=serial.stats.files_archived,
        files_retained_missing=serial.stats.files_missing_retained,
        project_keys=[], project_transitions=[item.to_dict() for item in serial.project_transitions],
    )
    parallel_payload = summary_payload(
        rows=parallel_rows["day"], total=summarize_records(parallel.records),
        generated_at=generated_at, range_name="all", group_by="day",
        sessions_dirs=parallel.session_dirs, files_scanned=len(parallel.files),
        storage_roots=[str(path) for path in parallel.session_dirs],
        files_archived=parallel.stats.files_archived,
        files_retained_missing=parallel.stats.files_missing_retained,
        project_keys=[], project_transitions=[item.to_dict() for item in parallel.project_transitions],
    )
    assert parallel_payload == serial_payload
    assert render_report_text(parallel, generated_at, tmp_path / "parallel.html") == render_report_text(
        serial, generated_at, tmp_path / "serial.html"
    )


def test_old_start_and_old_mtime_do_not_prune_recent_usage(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    old = datetime.now(UTC) - timedelta(days=30)
    os.utime(corpus.recent_old_metadata_path, (old.timestamp(), old.timestamp()))
    data = load_parallel(corpus, tmp_path / "cache", auto_transitions=False)
    ranged = filter_records_by_range(data.records, "7d", resolve_timezone("UTC"))
    assert any(record.file_path == corpus.recent_old_metadata_path for record in ranged)
    assert data.stats.files_parsed == data.stats.files_current
```

`render_report_text(data, generated_at, path) -> str` is fully defined in test support and calls `render_html_report` with the same summary/four aggregation inputs as `cli.handle_report`, then reads UTF-8 text. It normalizes only the caller-selected output path if that path is embedded; no totals/content are normalized.

- [ ] **Step 4: Verify and commit branch-safe tests**

Run:

```bash
uv run pytest tests/test_parallel_cache_equivalence.py tests/test_parallel_report_equivalence.py tests/test_parallel_cache_recovery.py tests/test_parallel_transition_equivalence.py tests/test_python_source_size.py -q
uv run pytest -q
git add tests/parallel_cache_test_support.py tests/test_parallel_cache_equivalence.py tests/test_parallel_report_equivalence.py
git commit -m "test: prove parallel refresh semantic equivalence"
```

Expected: PASS; the commit contains only executable tests/support and leaves the branch green.

### Task 6: Importable Acceptance, Audit, Freeze Support, And Native Smokes

**Files:**
- Create: `src/codex_usage/parallel_audit.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `src/codex_usage/__main__.py`
- Create: `scripts/parallel_cache_acceptance.py`
- Create: `scripts/packaged_parallel_cache_smoke.py`
- Modify: `scripts/build-macos-arm64-exe.sh`
- Modify: `scripts/build-windows-exe.ps1`
- Create: `tests/test_parallel_acceptance_scripts.py`
- Modify: `tests/test_github_actions_workflow.py`

**Interfaces:**
- Produces Audit And Acceptance Types exactly as declared.
- Keeps normal CLI outputs identical and adds only explicit suppressed audit output.
- Proves target OS/architecture and actual spawned child PIDs/overlap in source and frozen workflows.

- [ ] **Step 1: Write failing importability/audit/architecture tests**

`tests/test_parallel_acceptance_scripts.py` defines these typed helpers: `load_script_module(path: Path) -> ModuleType` executes the file under a unique non-main module name; `assert_importable_guard(path: Path, *, requires_freeze_support: bool) -> None` parses AST and requires exactly one `if __name__ == "__main__"` block, requires `multiprocessing.freeze_support()` before `main()` for the two spawn-capable scripts, and rejects top-level cache/CLI calls; `assert_no_sensitive_audit_keys(value: object) -> None` recursively rejects case-folded key fragments `path`, `session`, `thread`, `project`, `token`, `timestamp`, and `event`; and top-level `FixedDateTime(datetime)` returns `2026-07-31T12:00:00Z` from `now`.

Add these complete bodies:

```python
@pytest.mark.parametrize(
    ("relative_path", "requires_freeze_support"),
    [
        ("scripts/parallel_cache_acceptance.py", True),
        ("scripts/packaged_parallel_cache_smoke.py", True),
        ("scripts/parser_equivalence_check.py", False),
    ],
)
def test_acceptance_scripts_are_importable_and_guarded(
    relative_path: str,
    requires_freeze_support: bool,
) -> None:
    path = REPOSITORY_ROOT / relative_path
    module = load_script_module(path)
    assert callable(module.main)
    assert inspect.signature(module.main).return_annotation in {"int", int}
    assert_importable_guard(path, requires_freeze_support=requires_freeze_support)


def test_parallel_audit_does_not_change_summary_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codex_home = tmp_path / "codex"
    write_usage_corpus(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(cli_module, "datetime", FixedDateTime)
    assert cli_module.main(["summary", "--range", "all", "--json"]) == 0
    without_audit = json.loads(capsys.readouterr().out)
    audit_path = tmp_path / "audit.json"
    assert cli_module.main([
        "summary", "--range", "all", "--json", "--parallel-audit", str(audit_path)
    ]) == 0
    with_audit = json.loads(capsys.readouterr().out)
    assert with_audit == without_audit

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert tuple(audit) == (
        "version", "parent_pid", "sys_platform", "machine", "usage_run", "transition_run"
    )
    for run_key in ("usage_run", "transition_run"):
        assert tuple(audit[run_key]) == (
            "resolved_worker_count", "worker_pids", "max_concurrency",
            "used_serial_fallback", "infrastructure_error", "span_count", "file_error_count",
        )
    assert_no_sensitive_audit_keys(audit)


def test_actual_parallel_validator_rejects_every_disguised_serial_shape() -> None:
    parent_pid = 900
    overlap = (WorkerSpan(901, 0, 20), WorkerSpan(902, 5, 15))
    invalid = (
        ParallelRunReport(1, overlap, False, "", 0),
        ParallelRunReport(2, overlap, True, "OSError: failed", 0),
        ParallelRunReport(2, (WorkerSpan(parent_pid, 0, 20), WorkerSpan(902, 5, 15)), False, "", 0),
        ParallelRunReport(2, (WorkerSpan(901, 0, 20), WorkerSpan(901, 5, 15)), False, "", 0),
        ParallelRunReport(2, (WorkerSpan(901, 0, 5), WorkerSpan(902, 5, 10)), False, "", 0),
    )
    for report in invalid:
        with pytest.raises(RuntimeError, match="cold usage: actual process parallelism not observed"):
            require_actual_parallel(report, parent_pid=parent_pid, label="cold usage")
    require_actual_parallel(
        ParallelRunReport(2, overlap, False, "", 0), parent_pid=parent_pid, label="cold usage"
    )


def test_target_architecture_validator_is_exact() -> None:
    validate_target_architecture("darwin-arm64", sys_platform="darwin", machine="arm64")
    validate_target_architecture("win32-x64", sys_platform="win32", machine="AMD64")
    validate_target_architecture("win32-x64", sys_platform="win32", machine="x86_64")
    for target, sys_platform, machine in (
        ("darwin-arm64", "linux", "arm64"),
        ("darwin-arm64", "darwin", "x86_64"),
        ("win32-x64", "win32", "arm64"),
        ("win32-x64", "darwin", "x86_64"),
        ("linux-x64", "linux", "x86_64"),
    ):
        with pytest.raises(RuntimeError, match="unsupported target architecture"):
            validate_target_architecture(cast(Any, target), sys_platform=sys_platform, machine=machine)
```

Update `tests/test_github_actions_workflow.py` with full file-content assertions: both build scripts contain `packaged_parallel_cache_smoke.py`; Windows contains `RuntimeInformation.ProcessArchitecture`, `Architecture.X64`, and `--expected-target win32-x64`; macOS contains `uname -s`, `uname -m`, and `--expected-target darwin-arm64`; and each invocation precedes its existing packaged Task Transfer smoke. These are ordinary direct `read_text` assertions with no new fixture.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_parallel_acceptance_scripts.py tests/test_github_actions_workflow.py -q
```

Expected: imports/files/assertions fail because audit and scripts are absent.

- [ ] **Step 3: Implement audit and importable guarded source acceptance**

Add suppressed common option `--parallel-audit` of type `Path`. After cache load and before range filtering, call `write_parallel_audit` to atomically write the version-1 aggregate audit when present. Do not add audit fields to normal payloads.

`scripts/parallel_cache_acceptance.py` defines `main`, parses optional `--sessions-dir` and `--cache-dir`, opens a temporary cache when omitted, performs cold and warm `load_cached_session_data(auto_transitions=True)`, and calls `require_actual_parallel` for both cold usage and cold transition reports. It requires `(os.process_cpu_count() or 1) > 1`, no fallback, two child PIDs, overlap, and no parent PID. It also rejects fallback in either warm report; warm is allowed to resolve zero or one worker because reusable files are intentionally not resubmitted, so warm serial capacity cannot satisfy or replace either cold actual-parallel assertion. It verifies warm semantic digests match cold, every successful cold generation is reused, and warm retries only cold error rows. It prints one aggregate JSON object containing corpus files/bytes, elapsed values, stats/counts/digests, and run-report counts/PIDs only. Its guard is:

```python
if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
```

- [ ] **Step 4: Implement frozen entrypoint and packaged audit smoke**

Move `freeze_support()` before CLI import in `src/codex_usage/__main__.py`. The packaged smoke creates nine multi-megabyte JSONLs plus deterministic transition evidence, runs the executable cold with `summary --range all --json --parallel-audit <path>`, validates unchanged summary totals and audit actual-parallel conditions for usage and transitions, then runs warm and compares payloads. A 120-second subprocess timeout is a recursion deadlock guard, not a performance threshold. Serial mode or fallback always fails.

The smoke accepts exactly `--expected-target darwin-arm64|win32-x64`. For Darwin require `sys.platform == "darwin"` and `platform.machine().casefold() == "arm64"`. For Windows require `sys.platform == "win32"` and machine in `{"amd64", "x86_64"}`. Compare the packaged audit architecture too.

In PowerShell fail unless `[RuntimeInformation]::IsOSPlatform([OSPlatform]::Windows)` and `[RuntimeInformation]::ProcessArchitecture -eq [Architecture]::X64`. Then build and run smoke with `--expected-target win32-x64`. Keep the existing macOS OS/arm64 guard and pass `darwin-arm64`. Run the parallel smoke before the existing packaged transfer smoke.

- [ ] **Step 5: Verify branch integrity and the local matching package**

Run on every host:

```bash
uv run pytest tests/test_parallel_acceptance_scripts.py tests/test_github_actions_workflow.py tests/test_parallel_execution.py tests/test_parallel_report_equivalence.py tests/test_python_source_size.py -q
uv run pytest -q
```

Then run exactly one matching command locally:

```bash
# macOS Apple Silicon only
bash scripts/build-macos-arm64-exe.sh
```

```powershell
# Windows x64 only
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-windows-exe.ps1
```

Expected: source suites pass; the matching package proves target architecture, at least two actual spawned worker PIDs with overlap for both scans, no fallback, unchanged payload, warm reuse, and packaged transfer behavior. Do not claim the other platform locally.

- [ ] **Step 6: Commit**

```bash
git add src/codex_usage/parallel_audit.py src/codex_usage/cli.py src/codex_usage/__main__.py scripts/parallel_cache_acceptance.py scripts/packaged_parallel_cache_smoke.py scripts/build-macos-arm64-exe.sh scripts/build-windows-exe.ps1 tests/test_parallel_acceptance_scripts.py tests/test_github_actions_workflow.py
git commit -m "test: verify spawned workers in native packages"
```

### Task 7: ADR 0019 And Durable Documentation Contract

**Files:**
- Create: `docs/adr/0019-bounded-parallel-cache-refresh.md`
- Modify: `docs/adr/README.md`
- Create: `tests/test_parallel_cache_docs.py`

**Interfaces:**
- Records worker bounds/observability, infrastructure-only fallback, parent-global verification/SQLite, complete-generation recovery, no-checkpoint distinction, and native pre-publish gate.

- [ ] **Step 1: Write failing exact documentation assertions**

Require ADR/index text for: `os.process_cpu_count()`, `four`, `spawn`, `raw candidates`, `one global verification cache`, `parent process`, `state_5.sqlite`, `eight`, `complete file generation`, `serial fallback`, `infrastructure`, `per-file error`, `no byte offset`, `schema version 3`, `macOS Apple Silicon`, `Windows x64`, and `pre-publish`.

Run: `uv run pytest tests/test_parallel_cache_docs.py -q`

Expected: FAIL because ADR 0019 does not exist.

- [ ] **Step 2: Write concise ADR**

Use sections `Status`, `Context`, `Decision`, `Rejected Alternatives`, and `Consequences And Guardrails`. Context contains aggregate evidence only. Decision states the exact interfaces and recovery contract. Reject threads, range pruning, transition schema caching, worker path verification, and append checkpoints. Consequences require source/frozen PID-overlap proof, child SQLite guards, oracle equivalence, and manual non-publishing dual-native workflow before tag.

Index ADRs 0018 and 0019 in `docs/adr/README.md`.

- [ ] **Step 3: Verify branch integrity and commit**

Run:

```bash
uv run pytest tests/test_parallel_cache_docs.py tests/test_python_source_size.py -q
uv run pytest -q
git add docs/adr/0019-bounded-parallel-cache-refresh.md docs/adr/README.md tests/test_parallel_cache_docs.py
git commit -m "docs: record parallel refresh recovery contract"
```

Expected: PASS and a docs/test-only green commit.

### Task 8: Self-Contained Oracle, Aggregate Acceptance, And 0.1.42 Handoff

**Files:**
- Create: `scripts/parser_equivalence_check.py`
- Create: `tests/test_parser_equivalence_tool.py`
- Temporary private root: created with `mktemp -d`, deleted by trap
- Temporary detached worktree: commit `1fbe7de`, removed by trap
- Append aggregate results: `.superpowers/sdd/2026-07-31-usage-parser-performance-and-0-1-42-release/parallel-cache-refresh-implementation-report.md`

**Interfaces:**
- Produces fresh bounded copies and separate oracle/current digest files in one temporary root.
- Never depends on `/tmp/codex-usage-parser-baseline.json` or a prior task's temporary state.
- Runs cold/warm acceptance from the guarded importable script and fails disguised serial execution.

- [ ] **Step 1: Write failing full-body parser tool tests**

In `tests/test_parser_equivalence_tool.py`, write five valid synthetic JSONLs with distinct byte sizes and use these complete tests: `test_capture_copies_rounded_bounded_sample_without_private_paths` calls `capture(..., limit=3, max_file_bytes=10_000)`, asserts copied indexes `000`, `001`, `002`, asserts each manifest object has exactly `fixture` and `size_bytes`, asserts no source-root text occurs in serialized manifest/output, and asserts only the manifest plus three fixture files exist. `test_digest_and_compare_use_requested_package_root` captures all five, calls `digest(manifest, REPOSITORY_ROOT / "src", current)`, asserts every digest object has exactly `fixture`, `size_bytes`, and `digest`, copies it to `oracle`, asserts `compare(oracle, current) == 0`, changes one hex digest in `current`, and asserts `compare(oracle, current) == 1`. `test_digest_rejects_output_outside_manifest_evidence_root` asserts `ValueError("path must remain under evidence root")` when `output_path` is not below `manifest_path.parent`; `test_compare_requires_oracle_and_current_in_one_evidence_root` asserts the same error when the two inputs do not share one parent. `test_import_is_lazy_and_guarded` runs `runpy.run_path(script, run_name="parser_equivalence_import_test")` in a clean subprocess and asserts `codex_usage` is absent from `sys.modules`; it also calls `assert_importable_guard(script, requires_freeze_support=False)`. All test data is synthetic and deleted by `tmp_path`.

- [ ] **Step 2: Implement guarded parser equivalence tool**

`scripts/parser_equivalence_check.py` has subcommands and exact signatures:

```text
capture(source_root: Path, evidence_root: Path, *, limit: int, max_file_bytes: int) -> Path
digest(manifest_path: Path, package_root: Path, output_path: Path) -> Path
compare(oracle_path: Path, current_path: Path) -> int
main(argv: list[str] | None = None) -> int
```

Capture sorts eligible source files by `(size_bytes, casefolded path)`, samples at most 100 evenly using the original rounded-index rule, copies each to `evidence_root/fixtures/{index:03d}.jsonl`, and writes no source path/content to the manifest. Digest starts a fresh process, inserts the requested `src` root before importing `codex_usage.parser`, hashes `repr(parse_session_file(fixture))`, and writes fixture/size/digest only. Compare requires identical ordered entries/digests. The guarded script contains no spawn/cache work.

- [ ] **Step 3: Verify tooling and branch integrity, then commit**

Run:

```bash
uv run pytest tests/test_parser_equivalence_tool.py tests/test_python_source_size.py -q
uv run pytest -q
git add scripts/parser_equivalence_check.py tests/test_parser_equivalence_tool.py
git commit -m "test: add self-contained parser equivalence oracle"
```

Expected: PASS; script/test remain below 500 lines.

- [ ] **Step 4: Run fresh detached-oracle equivalence and delete all evidence**

Run from the repository root:

```bash
set -euo pipefail
evidence_root="$(mktemp -d "${TMPDIR:-/tmp}/codex-usage-equivalence.XXXXXX")"
oracle_worktree="$(mktemp -d "${TMPDIR:-/tmp}/codex-usage-oracle.XXXXXX")"
cleanup() {
  git worktree remove --force "$oracle_worktree" >/dev/null 2>&1 || true
  rm -rf "$evidence_root" "$oracle_worktree"
}
trap cleanup EXIT INT TERM

git worktree add --detach "$oracle_worktree" 1fbe7de
uv run python scripts/parser_equivalence_check.py capture \
  --source-root "$HOME/.codex/sessions" \
  --evidence-root "$evidence_root" \
  --limit 100 \
  --max-file-bytes 10485760
uv run python scripts/parser_equivalence_check.py digest \
  --manifest "$evidence_root/manifest.json" \
  --package-root "$oracle_worktree/src" \
  --output "$evidence_root/oracle.json"
uv run python scripts/parser_equivalence_check.py digest \
  --manifest "$evidence_root/manifest.json" \
  --package-root "$PWD/src" \
  --output "$evidence_root/current.json"
uv run python scripts/parser_equivalence_check.py compare \
  --oracle "$evidence_root/oracle.json" \
  --current "$evidence_root/current.json"
cleanup
trap - EXIT INT TERM
test ! -e "$evidence_root"
test ! -e "$oracle_worktree"
```

Expected: compare reports only aggregate fixture count/bytes and `equivalent=true`; detached worktree and every private copy/manifest/digest are absent afterward.

- [ ] **Step 5: Run importable aggregate cold/warm acceptance**

Quiesce session writes and run, never from stdin:

```bash
uv run python scripts/parallel_cache_acceptance.py
```

Expected: exit zero only when `(os.process_cpu_count() or 1) > 1`, cold usage and transition reports each resolve more than one worker, contain at least two overlapping non-parent child PIDs, and have no fallback. Both warm reports must also have no fallback; their worker count may be zero or one because reusable files are not submitted. Cold/warm semantic digests match; warm reuses every successful generation and retries only error rows. Output/report evidence is aggregate only. Record elapsed observations without a hard CI time assertion. If same-machine/corpus performance is not materially better than the prior 171-second interrupted run, stop and write a new aggregate diagnostic.

- [ ] **Step 6: Run complete verification**

Run:

```bash
git diff --check
uv run pytest -q
```

Expected: PASS. Do not create another commit for ignored implementation evidence.

#### Release Handoff: Return To Original Task 3, Prepare 0.1.42, And Gate Publish

**Files:**
- Resume original Task 3 acceptance using Task 8's fresh oracle result, largest-file observation, and real report.
- Modify exact release files from original Task 4: `pyproject.toml`, `uv.lock`, both extension package manifests, both changelogs, both READMEs, `docs/release.md`, and release contract tests.
- Verify `.github/workflows/package-vsix.yml` after merged code is pushed and before tagging.

**Interfaces:**
- Completes original Task 3 without inherited temporary evidence.
- Produces exact Preview `0.1.42` release copy/assertions.
- Requires local matching-native evidence first, then both native CI jobs in a non-publishing pushed-main run, then tag/publication.

- [ ] **Step 7: Finish original Task 3 measurements without stale baseline dependency**

Task 8's detached-oracle comparison replaces original Task 3 Step 1. Time the largest active JSONL with the unchanged parser and run:

```bash
/usr/bin/time -p uv run codex-usage report --range 7d --output /tmp/codex-usage-7d-performance.html
test -s /tmp/codex-usage-7d-performance.html
rm -f /tmp/codex-usage-7d-performance.html
uv run pytest -q
```

Expected: report completes, output is removed, and suite passes. Record only size/record/time aggregates.

- [ ] **Step 8: Write RED release assertions with exact copy**

Set release tests to require version/date `0.1.42`/`2026-07-31`, `preview === true`, and these exact changelog bullets in both changelogs:

```markdown
- Listed only active user-visible root tasks in Task Transfer while keeping subagent usage in dashboard totals.
- Deferred complete task hashing and conflict planning until after selection by replacing browse-time usage parsing and all-task hashing with metadata-only inventory.
- Skipped JSON decoding for irrelevant Codex events without changing usage totals, pricing, cache schema, or aggregation behavior.
- Refreshed invalidated usage caches with at most four whole-file worker processes and parent-only eight-file atomic commits, retaining complete prior generations on failure without adding offsets, range pruning, or schema changes.
```

Require both READMEs' Performance Cache sections to contain: `complete files from byte zero`, `at most four worker processes`, `SQLite remains in the parent process`, `eight complete-file replacements`, `committed batches are reusable after interruption`, and `no within-file checkpoint or range pruning`. Require `docs/release.md` to list the packaged audit's non-parent PID/overlap/no-fallback checks and the pre-publish non-publishing native workflow gate.

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py tests/test_parallel_cache_docs.py -q
cd extensions/vscode && npm run build && npm run typecheck:contracts && node --test --test-name-pattern='package metadata' test/core.test.js
```

Expected: FAIL only because release metadata/docs still describe `0.1.41` and lack new copy.

- [ ] **Step 9: Apply exact Preview release metadata and documentation**

Run `uv version 0.1.42`, `uv lock`, and `npm version 0.1.42 --no-git-tag-version`. Add heading `## 0.1.42 - 2026-07-31 - Faster Root-Task Transfer And Usage Refresh` with the exact four bullets above to both changelogs. Preserve historical Preview wording. Add exact README/release statements required by Step 2 and keep `preview: true`.

Run full Python and extension suites, then commit:

```bash
uv run pytest -q
cd extensions/vscode && npm test && npm run test:registration-smoke
cd ../..
git add pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json CHANGELOG.md extensions/vscode/CHANGELOG.md README.md extensions/vscode/README.md docs/release.md tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py extensions/vscode/test/core.test.js
git commit -m "chore: prepare 0.1.42 performance release"
```

Expected: all suites pass and release remains Preview.

- [ ] **Step 10: Review, merge locally, and prove only the matching native package**

Complete original Task 5 review/merge steps. On local `main`, run full Python/extension suites and only the matching Task 6 native package command. Do not claim the other native target yet.

- [ ] **Step 11: Push merged main and run both native jobs without publishing**

Run:

```bash
git push origin main
gh workflow run package-vsix.yml --ref main -f publish=false
run_id=""
for attempt in {1..12}; do
  run_id="$(gh run list --workflow package-vsix.yml --branch main --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
  test -n "$run_id" && break
  sleep 5
done
test -n "$run_id"
gh run watch "$run_id" --exit-status
gh run view "$run_id" --json conclusion,jobs,url
```

Expected: Windows x64 and macOS Apple Silicon test/package jobs succeed, each packaged audit proves target architecture plus two overlapping child PIDs with no fallback, and the publish job is skipped because `publish=false`. This is the required two-platform pre-publish evidence and occurs only after the workflow changes exist on pushed `main`.

- [ ] **Step 12: Tag and publish Preview only after the pre-publish gate**

Run:

```bash
git tag -a v0.1.42 -m "v0.1.42 Task Transfer and usage refresh performance release"
git push origin v0.1.42
```

Watch the tag-triggered workflow through both repeated native jobs and Marketplace publication as specified in original Task 5. Report the non-publishing gate URL, publishing URL, local matching-native result, aggregate cold/warm measurements, and manual checklist. Stop before `1.0.0` or Preview removal.

## Completion Gate

The revised addendum is complete only when:

- all request/result/report/candidate/state/audit interfaces are fully typed, pickle-safe, and implemented at module top level;
- `os.process_cpu_count()` resolves a deterministic cap of four and tests prove more than one actual overlapping non-parent child PID;
- infrastructure fallback is observable and ordinary per-file errors do not fallback or restart successful work;
- every SQLite call remains parent-only, proven by child-local spawn guards plus static import/dependency scans;
- transition workers emit raw candidates and one parent cache verifies JSONL then state evidence in global deterministic order;
- parallel transitions equal the frozen untouched serial oracle, not expectations built from new helpers;
- complete-file replacements commit in parent-owned groups of eight, retain old successful rows, and preserve reusable committed groups after interruption;
- full serial/parallel stats, summaries, errors, retained-missing state, normalized schema text/version, transitions, aggregations, payloads, and HTML are exactly equal;
- an old-start/old-mtime file with recent usage remains included in a seven-day range;
- source acceptance runs from a guarded importable script and fails serial/fallback/disguised execution;
- macOS arm64 and Windows x64 package smokes reject wrong architecture and prove actual spawned PID overlap;
- fresh bounded private fixtures compare current parser digests with detached commit `1fbe7de`, then all evidence/worktrees are deleted;
- no source/test/script file changed by the addendum reaches 500 lines and every task commit leaves the full suite green;
- cache schema, usage/fork/subagent/pricing/aggregation semantics, no-range-pruning, and no-within-file-checkpoint constraints remain intact;
- ADR 0019 records the durable contract;
- original Task 3 finishes, exact Preview `0.1.42` copy/assertions pass, pushed-main non-publishing native CI succeeds before tagging, and publication stops before stable promotion.
