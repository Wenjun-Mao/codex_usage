# Flat Single-Process Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the version-1 per-thread sync bundle and repeated status/import/export launches with a flat, byte-preserving version-2 store executed by one plan-driven process.

**Architecture:** Convert `codex_usage.sync` into a focused subpackage containing portable paths, retried filesystem I/O, the remote store, local inventory, three-way planner, local base state, and transaction runner. The CLI loads the cached Codex inventory once and exposes only `sync status` and `sync run`; the VS Code extension passes project keys or explicit thread ids directly to one child process and consumes structured progress events.

**Tech Stack:** Python 3.13, dataclasses, `pydantic-settings`, `tenacity`, pytest, TypeScript 5.7, Node test runner, VS Code extension APIs, PyInstaller one-file binaries, GitHub Actions native Windows x64 and macOS arm64 runners.

## Global Constraints

- Preserve each selected source JSONL byte-for-byte as one file under `conversations/`; never split, combine, normalize, summarize, or rewrite its events.
- Store remote metadata only in `sync-index.json` with `format_version: 2`; do not create per-thread directories or sidecars.
- Treat conversation JSONLs as durable data and the index as a repairable catalog. Never infer deletion from a missing or stale index entry.
- Preserve ADR 0008 three-way byte-prefix fast-forwards and stop all authoritative writes when any selected conversation is a true conflict.
- Detect the version-1 `threads/` layout and return cleanup instructions. Do not add a migration reader or automatic cleanup.
- Build one local inventory per command and share one plan across pull and push execution.
- Use bounded `tenacity` exponential-backoff retries only for transient idempotent filesystem operations. Do not retry semantic conflicts, malformed data, missing referenced files, or concurrency validation failures.
- Begin every new Python module with `from __future__ import annotations` and use Python 3.13 built-in collection/union typing.
- Support Windows x64 and macOS Apple Silicon only. Do not add Intel macOS packaging.
- Keep sync off until configured and preserve both explicit-conversation and all-conversations-in-selected-projects modes.
- Add no provider API, daemon, record-level merge, SQLite sync, auth sync, or automatic remote deletion.
- All implementation subagents must use GPT-5.6 with reasoning effort medium or higher and must be closed when their task and reviews finish.
- Follow TDD for behavior changes and run the full Python and VS Code test suites after each major slice.

## File Map

**Python sync package**

- `src/codex_usage/sync/__init__.py`: small public facade exporting `run_sync`, `sync_status`, and result models.
- `src/codex_usage/sync/constants.py`: format version, index filename, and conversation directory.
- `src/codex_usage/sync/errors.py`: typed semantic store/concurrency errors.
- `src/codex_usage/sync/models.py`: snapshots, index entries, inventory, plan, progress, counts, timings, and results.
- `src/codex_usage/sync/paths.py`: portable remote filename mapping, safe local target resolution, state and backup paths.
- `src/codex_usage/sync/io.py`: hashing, atomic file operations, JSON parsing, and bounded transient-I/O retries.
- `src/codex_usage/sync/store.py`: flat remote inventory, repair, validation, conversation writes, and one final index commit.
- `src/codex_usage/sync/inventory.py`: one local inventory build and union of explicit/project-selected local and remote ids.
- `src/codex_usage/sync/state.py`: local three-way base records, backups, local session-index merge, and memory diagnostics.
- `src/codex_usage/sync/planner.py`: shared three-way/prefix classification used by status and run.
- `src/codex_usage/sync/runner.py`: conflict preflight, pull-before-push execution, progress, diagnostics, and outcomes.

**CLI and extension**

- `src/codex_usage/cli.py`: replace import/export handlers with one run handler and project-aware status.
- `extensions/vscode/src/syncProtocol.ts`: CLI argument builders and strict parsing for progress, status, and final results.
- `extensions/vscode/src/syncProcess.ts`: one spawned process, line-buffered stderr progress, and final stdout handling.
- `extensions/vscode/src/core.ts`: retain settings/UX helpers; remove sync subprocess protocol responsibilities.
- `extensions/vscode/src/extension.ts`: call the one-process client directly and update truthful sync phases.

**Tests and durable docs**

- `tests/test_sync_store.py`: storage schema, repair, safety, retries, and optimistic concurrency.
- `tests/test_sync_planner.py`: selection and three-way planner matrix.
- `tests/test_sync.py`: transaction-level round trips, conflict preflight, backups, and operation counts.
- `tests/test_cli.py`: public command replacement, structured output, and new-machine pull.
- `extensions/vscode/test/syncProtocol.test.js`: argument and protocol parsing.
- `extensions/vscode/test/syncProcess.test.js`: chunked progress and exactly-one-process behavior.
- `docs/adr/0011-flat-single-process-sync.md`: durable decision and consequences.
- `README.md` and `extensions/vscode/README.md`: version-2 layout, cleanup, and large-task continuation scenario.
- `scripts/smoke-test-packaged-sync.py`: native packaged push/pull smoke test called by both build scripts.

---

### Task 1: Convert The Existing Sync Module Into A Package

**Files:**
- Move: `src/codex_usage/sync.py` to `src/codex_usage/sync/__init__.py`
- Test: `tests/test_sync.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing imports of `codex_usage.sync`.
- Produces: the same temporary module surface from a package path, allowing later focused modules without changing callers twice.

- [ ] **Step 1: Record the focused baseline**

Run:

```bash
uv run pytest tests/test_sync.py tests/test_cli.py -q
```

Expected: all existing sync and CLI tests pass.

- [ ] **Step 2: Perform the mechanical package move**

Run:

```bash
mkdir -p src/codex_usage/sync
git mv src/codex_usage/sync.py src/codex_usage/sync/__init__.py
```

Do not change behavior in this step. Imports such as `from codex_usage.sync import sync_status` must continue to resolve.

- [ ] **Step 3: Verify the package move**

Run:

```bash
uv run pytest tests/test_sync.py tests/test_cli.py -q
```

Expected: the same tests pass with `codex_usage.sync.__file__` ending in `sync/__init__.py`.

- [ ] **Step 4: Commit the structural checkpoint**

```bash
git add src/codex_usage/sync tests/test_sync.py tests/test_cli.py
git commit -m "refactor: make sync a focused package"
```

### Task 2: Add Version-2 Models, Portable Paths, And Retried I/O

**Files:**
- Create: `src/codex_usage/sync/constants.py`
- Create: `src/codex_usage/sync/errors.py`
- Create: `src/codex_usage/sync/models.py`
- Create: `src/codex_usage/sync/paths.py`
- Create: `src/codex_usage/sync/io.py`
- Create: `tests/test_sync_store.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: `SYNC_FORMAT_VERSION = 2`, `portable_thread_filename(thread_id: str) -> str`, `safe_session_target_path(session_dir: Path, relative_path: str) -> Path | None`, `snapshot_file(path: Path | None) -> SyncFileSnapshot`, `atomic_copy(source: Path, target: Path) -> None`, and `atomic_write_json(path: Path, value: dict[str, Any]) -> None`.
- Produces errors: `SyncStoreError`, `LegacySyncLayoutError`, `MalformedSyncIndexError`, `MissingRemoteConversationError`, `ConcurrentLocalChangeError`, and `ConcurrentRemoteChangeError`.
- Consumed by: Tasks 3 through 7.

- [ ] **Step 1: Write failing path and byte-preservation tests**

Add tests with these exact behavioral assertions:

```python
def test_portable_thread_filename_is_stable_and_windows_safe() -> None:
    assert portable_thread_filename("thread-1") == "thread-1.jsonl"
    assert portable_thread_filename("CON").startswith("id-")
    assert portable_thread_filename("Thread-1").startswith("id-")
    assert portable_thread_filename("Owner/Repo").startswith("id-")
    assert portable_thread_filename("Owner/Repo") == portable_thread_filename("Owner/Repo")
    assert "/" not in portable_thread_filename("Owner/Repo")


def test_safe_session_target_path_rejects_escape_and_absolute_paths(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    assert safe_session_target_path(sessions, "2026/07/13/thread.jsonl") == sessions / "2026/07/13/thread.jsonl"
    assert safe_session_target_path(sessions, "../outside.jsonl") is None
    assert safe_session_target_path(sessions, "/tmp/outside.jsonl") is None
    assert safe_session_target_path(sessions, "C:\\outside.jsonl") is None


def test_atomic_copy_preserves_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    target = tmp_path / "remote" / "thread-1.jsonl"
    source.write_bytes(b'{"type":"session_meta"}\n\xff\x00')
    atomic_copy(source, target)
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob("*.tmp"))


def test_atomic_write_retries_transient_replace_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "sync-index.json"
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("cloud folder is temporarily busy")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    atomic_write_json(target, {"format_version": 2, "threads": {}})
    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8"))["format_version"] == 2
```

- [ ] **Step 2: Run the tests and confirm the new package pieces are absent**

Run:

```bash
uv run pytest tests/test_sync_store.py -q
```

Expected: collection fails because `codex_usage.sync.paths` and `codex_usage.sync.io` do not exist.

- [ ] **Step 3: Add the required retry dependency**

Run:

```bash
uv add "tenacity>=9.1.2"
```

Expected: `pyproject.toml` and `uv.lock` include `tenacity` as a runtime dependency.

- [ ] **Step 4: Implement constants, errors, and path contracts**

Use these constants and signatures:

```python
SYNC_FORMAT_VERSION = 2
SYNC_INDEX_FILENAME = "sync-index.json"
SYNC_CONVERSATIONS_DIRNAME = "conversations"


def portable_thread_filename(thread_id: str) -> str:
    value = thread_id.strip()
    stem = value.split(".", 1)[0].upper()
    if value == value.casefold() and _SAFE_THREAD_ID.fullmatch(value) and stem not in WINDOWS_RESERVED_NAMES:
        return f"{value}.jsonl"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"id-{digest}.jsonl"
```

The safe-id expression must permit only `[A-Za-z0-9._-]`, require an alphanumeric first character, and cap the id at 120 characters before the `.jsonl` suffix. Direct readable filenames are allowed only when the id is already lowercase, preventing case-insensitive Windows collisions. Keep the original id only in the index.

- [ ] **Step 5: Implement typed models and retried I/O**

Define immutable dataclasses for `SyncFileSnapshot`, `RemoteThreadEntry`, `RemoteIndex`, `RemoteInventory`, `LocalInventory`, `LocalSyncState`, `SyncIssue`, `SyncPlanItem`, `SyncPlan`, `SyncProgressEvent`, `SyncCounts`, `SyncTimings`, and `SyncRunResult`. Every external payload model gets a `to_dict()` method; index models also get strict `from_dict()` constructors. Lock the inventory contracts to these fields:

```python
@dataclass(frozen=True)
class SyncFileSnapshot:
    path: Path | None
    exists: bool
    sha256: str = ""
    size_bytes: int = 0


@dataclass(frozen=True)
class RemoteThreadEntry:
    thread_id: str
    file: str
    source_relative_path: str
    index_entry: dict[str, Any]
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    sha256: str
    size_bytes: int
    session_updated_at: str
    exported_at: str
    source_machine_id: str


@dataclass(frozen=True)
class RemoteIndex:
    format_version: int
    updated_at: str
    threads: dict[str, RemoteThreadEntry]


@dataclass(frozen=True)
class RemoteInventory:
    persisted_index: RemoteIndex
    index: RemoteIndex
    index_snapshot: SyncFileSnapshot
    files: dict[str, SyncFileSnapshot]
    repaired_thread_ids: tuple[str, ...]
    issues: tuple[SyncIssue, ...]


@dataclass(frozen=True)
class LocalInventory:
    session_dirs: tuple[Path, ...]
    threads: dict[str, ThreadInfo]
    index_entries: dict[str, dict[str, Any]]
    discovered_count: int


@dataclass(frozen=True)
class LocalSyncState:
    thread_id: str
    sync_dir_fingerprint: str
    base_sha256: str
    base_size_bytes: int
    base_updated_at: str
    last_remote_sha256: str
    last_local_sha256: str
    source_relative_path: str
    project_key: str
    project_label: str
    synced_at: str


@dataclass(frozen=True)
class SyncIssue:
    code: str
    message: str
    thread_id: str = ""


@dataclass(frozen=True)
class SyncPlanItem:
    thread_id: str
    state: str
    action: str
    reason: str
    local: SyncFileSnapshot
    remote: SyncFileSnapshot
    base_sha256: str
    updated_at: str
    source_relative_path: str
    project_key: str
    project_label: str
    memory_database_rows: int
    expected_remote_entry: RemoteThreadEntry | None


@dataclass(frozen=True)
class SyncPlan:
    items: tuple[SyncPlanItem, ...]
    issues: tuple[SyncIssue, ...]
    discovered_count: int
    remote_count: int
    selected_count: int


@dataclass(frozen=True)
class SyncProgressEvent:
    type: str
    phase: str


@dataclass(frozen=True)
class SyncCounts:
    discovered: int
    selected: int
    remote: int
    pulled: int
    pushed: int
    unchanged: int
    conflicts: int
    issues: int


@dataclass(frozen=True)
class SyncTimings:
    discovery: int
    planning: int
    pull: int
    push: int
    index: int
    total: int


@dataclass(frozen=True)
class SyncRunResult:
    outcome: str
    counts: SyncCounts
    timings_ms: SyncTimings
    threads: tuple[SyncPlanItem, ...]
    pulled: tuple[str, ...]
    pushed: tuple[str, ...]
    issues: tuple[SyncIssue, ...]
```

`RemoteInventory.persisted_index` is the exact catalog read from disk and is used for optimistic comparisons. `RemoteInventory.index` is the effective in-memory catalog after safe repair. `RemoteInventory.files` is keyed by original thread id after index validation or safe `session_meta` reconstruction, never by the portable filename.

`SyncRunResult` provides `blocked(plan: SyncPlan, timings: SyncTimings) -> SyncRunResult`, `failed(plan: SyncPlan, runtime_issue: SyncIssue, pulled: tuple[str, ...], pushed: tuple[str, ...], timings: SyncTimings) -> SyncRunResult`, and `completed(plan: SyncPlan, pulled: tuple[str, ...], pushed: tuple[str, ...], timings: SyncTimings) -> SyncRunResult` constructors so Task 6 has one place to derive counts and serialized payload fields.

`SyncPlan` provides `expected_remote_entries() -> dict[str, RemoteThreadEntry | None]`, `expected_remote_snapshots() -> dict[str, SyncFileSnapshot]`, `has_conflicts`, and `has_issues`; all derive only from its immutable `items` and `issues`.

`SyncPlan.to_dict()` returns `{"threads": [...], "issues": [...]}`. Each serialized item keeps the existing flat diagnostics (`thread_id`, `state`, `action`, `reason`, local/remote/base hashes and paths, project fields, source-relative path, update time, and memory warning). `SyncRunResult.to_dict()` returns exactly `outcome`, `counts`, `timings_ms`, `threads`, `pulled`, `pushed`, and `issues`, matching the Task 8 TypeScript parser.

Wrap only filesystem byte reads, temporary writes, copies, and `Path.replace` operations with:

```python
@retry(
    retry=retry_if_exception_type(OSError),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
```

Parse JSON after the retried read returns so `json.JSONDecodeError` is never retried. Temporary files must be siblings of the target and must be removed in `finally`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_sync_store.py -q
```

Expected: path, atomic-copy, and model round-trip tests pass.

- [ ] **Step 7: Commit the foundation**

```bash
git add pyproject.toml uv.lock src/codex_usage/sync tests/test_sync_store.py
git commit -m "feat: add version 2 sync primitives"
```

### Task 3: Implement The Flat Remote Store And Repair Rules

**Files:**
- Create: `src/codex_usage/sync/store.py`
- Modify: `src/codex_usage/sync/models.py`
- Modify: `tests/test_sync_store.py`

**Interfaces:**
- Consumes: version-2 models, paths, and I/O from Task 2.
- Produces: `RemoteStore(root: Path)`, `load_inventory() -> RemoteInventory`, `validate_selected(expected_entries: dict[str, RemoteThreadEntry | None], expected_files: dict[str, SyncFileSnapshot]) -> None`, `write_conversation(source: Path, filename: str) -> SyncFileSnapshot`, and `commit_index(base: RemoteInventory, changed: dict[str, RemoteThreadEntry], written: dict[str, SyncFileSnapshot]) -> RemoteIndex`.
- Produces: repair issues with codes `missing_remote_file` and `unindexed_unreadable`; semantic exceptions for legacy layout, malformed index, and visible concurrent changes.

- [ ] **Step 1: Add failing flat-store and legacy-layout tests**

```python
def test_remote_store_loads_empty_folder_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    store = RemoteStore(root)
    inventory = store.load_inventory()
    assert inventory.index.format_version == 2
    assert inventory.index.threads == {}
    assert inventory.files == {}
    assert not root.exists()


def test_remote_store_rejects_version_1_layout_without_mutating_it(tmp_path: Path) -> None:
    legacy = tmp_path / "sync" / "threads" / "thread-1"
    legacy.mkdir(parents=True)
    (legacy / "session.jsonl").write_text("{}\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    with pytest.raises(LegacySyncLayoutError, match="empty the sync folder"):
        RemoteStore(tmp_path / "sync").load_inventory()
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
```

Also add tests that a malformed `sync-index.json` raises `MalformedSyncIndexError`, two thread ids cannot claim the same remote filename, an indexed missing file yields `missing_remote_file`, a stale indexed hash/size is repaired from the existing JSONL, a thread-id mismatch between index and JSONL becomes an issue, and an unindexed valid JSONL is reconstructed from its `session_meta` without being rewritten.

- [ ] **Step 2: Run the store tests to verify failure**

Run:

```bash
uv run pytest tests/test_sync_store.py -q
```

Expected: failures show `RemoteStore` is not implemented.

- [ ] **Step 3: Implement one planning read and repairable inventory**

`load_inventory()` must execute in this order:

```python
def load_inventory(self) -> RemoteInventory:
    self._reject_legacy_layout()
    index_snapshot = snapshot_file(self.index_path)
    persisted_index = self._read_index(index_snapshot)
    files = self._snapshot_conversation_files()
    index, repaired_thread_ids, issues = self._reconcile_index(persisted_index, files)
    return RemoteInventory(
        persisted_index=persisted_index,
        index=index,
        index_snapshot=index_snapshot,
        files=files,
        repaired_thread_ids=tuple(repaired_thread_ids),
        issues=tuple(issues),
    )
```

Validate every indexed `file` as a relative direct child of `conversations/`. When the referenced JSONL exists, verify its `session_meta` thread id matches the index key; refresh stale hash and size fields from the file without rewriting it. For an unindexed valid JSONL, read `session_meta`, retain its original thread id, derive project identity through existing `resolve_project_identity`, and use `synced/<portable-thread-filename>` as the repair fallback for an unavailable original source path. For unreadable or mismatched identity, append an issue and leave bytes untouched.

- [ ] **Step 4: Implement writes and optimistic index commit**

`write_conversation()` atomically copies bytes and returns the resulting snapshot. `commit_index()` re-reads the latest index and merges unrelated latest entries. Selected index entries must still match `base.persisted_index`; selected files written by this run must match `written`, while selected files not written by this run must still match `base.files`. Then overlay `changed`, include safely repaired entries from `base.index`, set `format_version` to 2, and perform one atomic replacement.

Raise `ConcurrentRemoteChangeError` when a selected entry or file changed after planning. Never remove an entry or JSONL merely because it is absent from `changed`.

- [ ] **Step 5: Verify store behavior**

Run:

```bash
uv run pytest tests/test_sync_store.py -q
```

Expected: flat layout, repair, malformed-data, legacy-layout, and concurrency tests pass.

- [ ] **Step 6: Commit the remote store**

```bash
git add src/codex_usage/sync/store.py src/codex_usage/sync/models.py tests/test_sync_store.py
git commit -m "feat: add flat remote conversation store"
```

### Task 4: Build One Local Inventory And Resolve Project Selections

**Files:**
- Create: `src/codex_usage/sync/inventory.py`
- Create: `tests/test_sync_planner.py`
- Modify: `src/codex_usage/sync/models.py`

**Interfaces:**
- Consumes: `CachedSessionData`, `list_threads_from_cached_data`, local index entries, and `RemoteInventory`.
- Produces: `build_local_inventory(data: CachedSessionData) -> LocalInventory` and `resolve_selected_thread_ids(local: LocalInventory, remote: RemoteInventory, project_keys: list[str], thread_ids: list[str]) -> tuple[str, ...]`.
- Guarantees: one call to `list_threads_from_cached_data` for each status/run command.

- [ ] **Step 1: Write failing selection tests**

Define these private builders at the top of `tests/test_sync_planner.py` so every object uses the Task 2 model contract:

```python
def _thread(thread_id: str, project_key: str = "repo", aliases: tuple[str, ...] = ()) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-13T12:00:00Z",
        session_path=Path("fixtures") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label=project_key,
        project_aliases=aliases,
        total_tokens=0,
        session_bytes=0,
        estimated_sync_bytes=4096,
    )


def _remote_entry(thread_id: str, project_key: str = "repo") -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"conversations/{thread_id}.jsonl",
        source_relative_path=f"synced/{thread_id}.jsonl",
        index_entry={"id": thread_id},
        project_key=project_key,
        project_label=project_key,
        project_aliases=(),
        sha256="",
        size_bytes=0,
        session_updated_at="2026-07-13T12:00:00Z",
        exported_at="2026-07-13T12:00:00Z",
        source_machine_id="machine-a",
    )


def _local_inventory(*threads: ThreadInfo) -> LocalInventory:
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads={item.thread_id: item for item in threads},
        index_entries={},
        discovered_count=len(threads),
    )


def _remote_inventory(*entries: RemoteThreadEntry) -> RemoteInventory:
    index = RemoteIndex(format_version=2, updated_at="", threads={item.thread_id: item for item in entries})
    return RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(path=None, exists=False),
        files={},
        repaired_thread_ids=(),
        issues=(),
    )
```

```python
def test_project_selection_unions_local_and_remote_threads() -> None:
    local = _local_inventory(
        _thread("local", project_key="https://github.com/example/demo", aliases=("/repo/demo",))
    )
    remote = _remote_inventory(
        _remote_entry("remote", project_key="https://github.com/example/demo")
    )
    selected = resolve_selected_thread_ids(
        local,
        remote,
        project_keys=["https://github.com/example/demo"],
        thread_ids=[],
    )
    assert selected == ("local", "remote")


def test_explicit_selection_is_exact_even_when_projects_are_available() -> None:
    local = _local_inventory(_thread("chosen"), _thread("not-chosen"))
    assert resolve_selected_thread_ids(local, _remote_inventory(), [], ["chosen"]) == ("chosen",)
```

Add a test that rebuilding local inventory after adding a conversation causes the same project selector to include the new id.

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
uv run pytest tests/test_sync_planner.py -q
```

Expected: import failure for `codex_usage.sync.inventory`.

- [ ] **Step 3: Implement local inventory and selector union**

Use this public shape:

```python
def build_local_inventory(data: CachedSessionData) -> LocalInventory:
    threads = list_threads_from_cached_data(data)
    return LocalInventory(
        session_dirs=tuple(data.session_dirs),
        threads={thread.thread_id: thread for thread in threads},
        index_entries=load_all_index_entries(data.session_dirs),
        discovered_count=len(data.files),
    )
```

Normalize project keys with existing `normalize_project_key`. A local thread matches its canonical key or aliases. A remote entry matches its canonical key or stored aliases. Return deduplicated ids in deterministic case-sensitive order: explicit ids first, then matching local ids sorted by id, then matching remote ids sorted by id.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_sync_planner.py tests/test_threads.py -q
```

Expected: selection and existing thread discovery tests pass.

- [ ] **Step 5: Commit inventory selection**

```bash
git add src/codex_usage/sync/inventory.py src/codex_usage/sync/models.py tests/test_sync_planner.py
git commit -m "feat: resolve sync projects from one inventory"
```

### Task 5: Extract Local State And Implement The Shared Planner

**Files:**
- Create: `src/codex_usage/sync/state.py`
- Create: `src/codex_usage/sync/planner.py`
- Modify: `src/codex_usage/sync/models.py`
- Modify: `tests/test_sync_planner.py`

**Interfaces:**
- Consumes: `LocalInventory`, `RemoteInventory`, selected ids, portable paths, and local base state.
- Produces: `LocalStateStore(session_dir: Path, sync_dir: Path)`, `classify_snapshots(local: SyncFileSnapshot, remote: SyncFileSnapshot, base_sha256: str) -> tuple[str, str, str]`, and `build_sync_plan(local: LocalInventory, remote: RemoteInventory, selected_thread_ids: tuple[str, ...], sync_dir: Path) -> SyncPlan`.
- Produces actions: `none`, `pull`, `push`, `skip`, `conflict`, or `issue` and states from ADR 0008 plus `issue`.

- [ ] **Step 1: Write the failing planner matrix**

Use one parameterized test with these exact cases. This complete helper keeps state classification independent from inventory construction:

```python
def _snapshot_bytes(tmp_path: Path, name: str, value: bytes | None) -> SyncFileSnapshot:
    path = tmp_path / name
    if value is None:
        return SyncFileSnapshot(path=path, exists=False)
    path.write_bytes(value)
    return snapshot_file(path)


@pytest.mark.parametrize(
    ("local", "remote", "base", "expected_state", "expected_action"),
    [
        (b"same", b"same", b"same", "synced", "none"),
        (b"base+local", b"base", b"base", "local_ahead", "push"),
        (b"base", b"base+remote", b"base", "remote_ahead", "pull"),
        (b"base+local", b"base", None, "fast_forward_push", "push"),
        (b"base", b"base+remote", None, "fast_forward_pull", "pull"),
        (b"left", b"right", b"base", "conflict", "conflict"),
        (b"local", None, None, "local_only", "push"),
        (None, b"remote", None, "remote_only", "pull"),
        (None, None, None, "missing", "skip"),
    ],
)
def test_planner_classifies_three_way_state(
    tmp_path: Path,
    local: bytes | None,
    remote: bytes | None,
    base: bytes | None,
    expected_state: str,
    expected_action: str,
) -> None:
    local_snapshot = _snapshot_bytes(tmp_path, "local.jsonl", local)
    remote_snapshot = _snapshot_bytes(tmp_path, "remote.jsonl", remote)
    base_sha256 = hashlib.sha256(base).hexdigest() if base is not None else ""
    state, action, _reason = classify_snapshots(local_snapshot, remote_snapshot, base_sha256)
    assert state == expected_state
    assert action == expected_action
```

Add tests for path traversal, duplicate local path preference, a missing referenced remote file becoming `issue`, and memory-row diagnostics remaining non-mutating.

- [ ] **Step 2: Verify the planner tests fail**

Run:

```bash
uv run pytest tests/test_sync_planner.py -q
```

Expected: failures identify missing state/planner APIs.

- [ ] **Step 3: Implement local state and backup helpers**

Move the existing sync-folder fingerprint and base-state behavior into `LocalStateStore`:

```python
class LocalStateStore:
    def __init__(self, session_dir: Path, sync_dir: Path) -> None:
        self.session_dir = session_dir
        self.sync_dir = sync_dir

    def read(self, thread_id: str) -> LocalSyncState | None:
        value = read_json_object(self.path_for(thread_id))
        return LocalSyncState.from_dict(value) if value is not None else None

    def write(self, state: LocalSyncState) -> None:
        if state.sync_dir_fingerprint != sync_dir_fingerprint(self.sync_dir):
            raise ValueError("Local sync state belongs to a different sync folder.")
        atomic_write_json(self.path_for(state.thread_id), state.to_dict())

    def record_success(self, item: SyncPlanItem, local: SyncFileSnapshot, remote: SyncFileSnapshot) -> None:
        self.write(local_state_from_success(item, local, remote, self.sync_dir))


def local_state_from_success(
    item: SyncPlanItem,
    local: SyncFileSnapshot,
    remote: SyncFileSnapshot,
    sync_dir: Path,
) -> LocalSyncState:
    base = local if local.exists else remote
    return LocalSyncState(
        thread_id=item.thread_id,
        sync_dir_fingerprint=sync_dir_fingerprint(sync_dir),
        base_sha256=base.sha256,
        base_size_bytes=base.size_bytes,
        base_updated_at=item.updated_at,
        last_remote_sha256=remote.sha256,
        last_local_sha256=local.sha256,
        source_relative_path=item.source_relative_path,
        project_key=item.project_key,
        project_label=item.project_label,
        synced_at=now_iso(),
    )
```

Keep backup-before-local-replace, conflict-candidate backup, local `session_index.jsonl` newest-entry merge, safe target paths, and read-only memory database diagnostics in this module.

- [ ] **Step 4: Implement one shared planner**

For each selected id, resolve local and remote snapshots once, load one base record, compute byte-prefix relation only when hashes differ, and apply the matrix from the test. Store the expected remote entry from `remote.persisted_index` and the effective file fingerprint on each `SyncPlanItem` for Task 6 concurrency validation; use `remote.index` for repaired metadata and selection.

Any store issue tied to a selected thread produces action/state `issue`. Unselected store issues remain visible in diagnostics but do not block selected work.

- [ ] **Step 5: Run planner and legacy regression tests**

Run:

```bash
uv run pytest tests/test_sync_planner.py tests/test_sync.py -q
```

Expected: planner tests pass; existing transaction tests still pass through the temporary legacy facade.

- [ ] **Step 6: Commit the shared planner**

```bash
git add src/codex_usage/sync/state.py src/codex_usage/sync/planner.py src/codex_usage/sync/models.py tests/test_sync_planner.py
git commit -m "feat: add shared three-way sync planner"
```

### Task 6: Implement The One-Transaction Runner

**Files:**
- Create: `src/codex_usage/sync/runner.py`
- Modify: `src/codex_usage/sync/__init__.py`
- Modify: `tests/test_sync.py`

**Interfaces:**
- Consumes: `CachedSessionData`, `RemoteStore`, local inventory, selector resolution, shared planner, and local state.
- Produces in `sync.runner`: `sync_status(data: CachedSessionData, sync_dir: Path, project_keys: list[str], thread_ids: list[str]) -> SyncPlan`.
- Produces in `sync.runner`: `run_sync(data: CachedSessionData, sync_dir: Path, project_keys: list[str], thread_ids: list[str], machine_id: str, discovery_ms: int = 0, on_progress: Callable[[SyncProgressEvent], None] | None = None) -> SyncRunResult`.

- [ ] **Step 1: Replace version-1 transaction tests with failing version-2 tests**

Keep the existing thread-listing tests, but replace direct `export_threads`/`import_threads` coverage with transaction tests like:

```python
def test_run_sync_pushes_flat_bytes_and_one_index(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    source = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    result = run_sync(data=data, sync_dir=tmp_path / "sync", project_keys=[], thread_ids=["thread-1"], machine_id="a")
    assert result.outcome == "completed"
    assert result.pushed == ("thread-1",)
    assert (tmp_path / "sync" / "conversations" / "thread-1.jsonl").read_bytes() == source.read_bytes()
    assert (tmp_path / "sync" / "sync-index.json").is_file()
    assert not (tmp_path / "sync" / "threads").exists()


def test_conflict_preflight_changes_no_authoritative_files(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(data=initial, sync_dir=sync_dir, project_keys=[], thread_ids=["thread-1"], machine_id="a")
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
    _append_token_event(local_path, "2026-07-13T12:01:00Z", 180)
    _append_token_event(remote_path, "2026-07-13T12:02:00Z", 240)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    local_before = local_path.read_bytes()
    remote_before = remote_path.read_bytes()
    result = run_sync(data=data, sync_dir=sync_dir, project_keys=[], thread_ids=["thread-1"], machine_id="a")
    assert result.outcome == "conflict"
    assert local_path.read_bytes() == local_before
    assert remote_path.read_bytes() == remote_before
```

Add tests for pull-before-push round trips, local backups, local session-index merge, a local source changing after planning, visible remote concurrent changes, and an interrupted unindexed JSONL being repaired on the next run.

- [ ] **Step 2: Add operation-count and phase tests**

Monkeypatch `runner.build_local_inventory` and `RemoteStore.load_inventory` with counters. For an empty remote and a large synthetic local selection, assert each is called once, `result.counts.pulled == 0`, and runner progress contains exactly `pushing` with no `pulling` event. Task 7 separately verifies the command-level `scanning` event emitted before cache discovery.

- [ ] **Step 3: Run transaction tests to verify failure**

Run:

```bash
uv run pytest tests/test_sync.py -q
```

Expected: failures show `run_sync` and the version-2 facade are not present.

- [ ] **Step 4: Implement the runner with conflict preflight**

Use this execution order:

```python
def run_sync(*, data, sync_dir, project_keys, thread_ids, machine_id, discovery_ms=0, on_progress=None):
    timer = PhaseTimer(discovery_ms=discovery_ms)
    local = build_local_inventory(data)
    store = RemoteStore(sync_dir)
    remote = store.load_inventory()
    selected = resolve_selected_thread_ids(local, remote, project_keys, thread_ids)
    plan = build_sync_plan(local, remote, selected, sync_dir)
    if plan.has_conflicts or plan.has_issues:
        save_conflict_candidates(plan)
        return SyncRunResult.blocked(plan, timings=timer.finish())
    validate_local_selected(plan)
    store.validate_selected(plan.expected_remote_entries(), plan.expected_remote_snapshots())
    pulled = execute_pulls(plan, local, remote, on_progress)
    pushed = execute_pushes(plan, local, store, machine_id, on_progress)
    commit_remote_index_once(plan, remote, store, pushed)
    return SyncRunResult.completed(
        plan,
        pulled=pulled,
        pushed=pushed.thread_ids,
        timings=timer.finish(),
    )
```

Define a private immutable `PushExecution` with `thread_ids: tuple[str, ...]`, `snapshots: dict[str, SyncFileSnapshot]`, and `entries: dict[str, RemoteThreadEntry]`. Define the private helpers with these signatures in the same module: `emit(callback: Callable[[SyncProgressEvent], None] | None, phase: str) -> None`, `save_conflict_candidates(plan: SyncPlan) -> None`, `validate_local_selected(plan: SyncPlan) -> None`, `execute_pulls(plan: SyncPlan, local: LocalInventory, remote: RemoteInventory, callback: Callable[[SyncProgressEvent], None] | None) -> tuple[str, ...]`, `execute_pushes(plan: SyncPlan, local: LocalInventory, store: RemoteStore, machine_id: str, callback: Callable[[SyncProgressEvent], None] | None) -> PushExecution`, and `commit_remote_index_once(plan: SyncPlan, remote: RemoteInventory, store: RemoteStore, pushed: PushExecution) -> None`. The final helper passes `pushed.entries` and `pushed.snapshots` into `RemoteStore.commit_index`, together with repaired index entries from `remote`. A private `PhaseTimer(discovery_ms: int)` records planning, pull, push, index, and total milliseconds and returns the Task 2 `SyncTimings` model from `finish()`.

Validate every selected local snapshot immediately before execution and again immediately before replacing or copying that specific local file. After a push copy, verify the source still matches its planned hash and the remote result matches the copied hash before adding it to `PushExecution`; otherwise raise `ConcurrentLocalChangeError`, convert it to an `issue` result at the runner boundary, and leave the new remote JSONL unindexed for safe repair on the next run.

Emit `pulling` only when pull actions exist and `pushing` only when push actions exist. Update each local base state only after that conversation's successful action. Commit the remote index once, after remote JSONL writes; skip the index write entirely when there are no pushed or safely repaired entries.

Catch `ConcurrentLocalChangeError`, `ConcurrentRemoteChangeError`, and typed store-state errors at the runner boundary and return `SyncRunResult.failed(...)` with any already completed thread ids. If remote inventory loading itself fails, construct an empty-item `SyncPlan` carrying that typed issue plus the known local discovery count, so JSON mode still receives a final structured result. Do not catch programmer errors or convert them into successful results.

- [ ] **Step 5: Expose the new runner without breaking the pre-cutover CLI**

Import and export `run_sync` from `sync.runner` while leaving the existing version-1 functions in `sync/__init__.py` until Task 7 changes their CLI caller. Do not add wrappers or migration behavior. New transaction tests import `run_sync`; the existing CLI can still import its old names for this one intermediate checkpoint.

- [ ] **Step 6: Run all Python sync tests**

Run:

```bash
uv run pytest -q
```

Expected: the complete Python suite passes, including the new version-2 runner and the still-buildable pre-cutover CLI.

- [ ] **Step 7: Commit the transaction runner**

```bash
git add src/codex_usage/sync tests/test_sync.py tests/test_sync_store.py tests/test_sync_planner.py
git commit -m "feat: run pull and push in one sync transaction"
```

### Task 7: Replace CLI Import And Export With `sync run`

**Files:**
- Modify: `src/codex_usage/cli.py`
- Modify: `src/codex_usage/sync/__init__.py`
- Modify: `src/codex_usage/threads.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_sync.py`
- Delete: `src/codex_usage/sync_io.py`
- Delete: `src/codex_usage/sync_constants.py`

**Interfaces:**
- Consumes: `run_sync`, `sync_status`, the existing cache loader, default machine id, project-key normalization, and automatic-transition settings.
- Produces: `codex-usage sync run --sync-dir PATH [--project-key KEY] [--thread-id ID] --json` and project-aware `sync status`.
- Exit contract: run returns 0 for `completed` and 2 for `conflict` or `issue`. Status returns 0 whenever it successfully emits a structured read-only plan, including conflicts or typed store issues such as a version-1 layout; argument and unexpected runtime failures still return 2.
- Stream contract: final JSON is stdout; progress events are JSONL on stderr with `{"type":"sync_progress","phase":"scanning|pulling|pushing"}`.

- [ ] **Step 1: Rewrite the CLI integration test first**

```python
def test_cli_sync_run_replaces_import_and_export(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    source_day = source_home / "sessions" / "2026" / "04" / "29"
    source_day.mkdir(parents=True)
    _write_session(source_day / "thread-1.jsonl", "thread-1", "/repo/first", 100)
    (source_home / "session_index.jsonl").write_text(
        json.dumps({"id": "thread-1", "thread_name": "First thread", "updated_at": "2026-04-29T10:05:00Z"}) + "\n",
        encoding="utf-8",
    )
    sync_dir = tmp_path / "sync"
    pushed = _run_cli(
        ["sync", "run", "--sync-dir", str(sync_dir), "--project-key", "/repo/first", "--json"],
        env={"CODEX_HOME": str(source_home)},
    )
    assert json.loads(pushed.stdout)["outcome"] == "completed"
    assert json.loads(pushed.stdout)["counts"]["pushed"] == 1
    assert '"phase":"scanning"' in pushed.stderr.replace(" ", "")
    assert '"phase":"pulling"' not in pushed.stderr.replace(" ", "")

    target_home = tmp_path / "target"
    pulled = _run_cli(
        ["sync", "run", "--sync-dir", str(sync_dir), "--project-key", "/repo/first", "--json"],
        env={"CODEX_HOME": str(target_home)},
    )
    assert json.loads(pulled.stdout)["counts"]["pulled"] == 1
    assert len(list((target_home / "sessions").rglob("*.jsonl"))) == 1
```

Add help assertions that `sync run` and `sync status` exist while `sync import`, `sync export`, and `--conflict-policy` do not.

- [ ] **Step 2: Run the CLI test and verify the public contract fails**

Run:

```bash
uv run pytest tests/test_cli.py::test_cli_sync_run_replaces_import_and_export -q
```

Expected: argparse rejects `sync run`.

- [ ] **Step 3: Implement shared sync selectors and one cache load**

Both run and status parsers receive repeatable optional `--project-key` and `--thread-id`, `--sync-dir`, `--json`, and `--no-auto-transitions`. Run additionally receives `--machine-id`.

The handler must reject an empty normalized selector set with `ValueError("Select at least one project key or thread id for sync.")`.

Immediately before `_load_session_data`, emit the scanning event and capture `perf_counter()`. Call `_sync_session_dirs(create=True)` for run and return the default sessions path without creating it for status. Pass the resulting `CachedSessionData` directly to the shared runner or planner; do not call `list_threads` again.

- [ ] **Step 4: Implement structured output and exit handling**

Use compact JSON progress lines with `flush=True` on stderr. In JSON mode, stdout must contain only the final result or plan object. Human mode prints one summary after completion.

Do not let cache fallback diagnostics masquerade as progress; they may remain ordinary stderr lines because the extension parser in Task 8 ignores lines without `type: "sync_progress"`.

- [ ] **Step 5: Remove the version-1 engine at the caller cutover**

Reduce `sync/__init__.py` to explicit exports from models and runner. Remove `ExportResult`, `ImportResult`, `export_threads`, `import_threads`, the old status implementation, and all `threads/<id>` remote path helpers. Keep the 4096-byte UI estimate as a private constant in `threads.py` so thread discovery does not import the sync package and form a cycle; delete `sync_io.py` and `sync_constants.py`.

Update thread-list tests to import `list_threads` from `codex_usage.threads`, not incidentally through `codex_usage.sync`. Update every remaining sync test to use the version-2 runner/store APIs.

- [ ] **Step 6: Run CLI and Python end-to-end tests**

Run:

```bash
uv run pytest -q
```

Expected: the complete Python suite passes and CLI help exposes only status/run mutation semantics.

- [ ] **Step 7: Commit the CLI replacement**

```bash
git add src/codex_usage/cli.py src/codex_usage/sync src/codex_usage/threads.py tests/test_cli.py tests/test_sync.py
git rm src/codex_usage/sync_io.py src/codex_usage/sync_constants.py
git commit -m "feat: expose one project-aware sync command"
```

### Task 8: Add A Focused TypeScript Sync Protocol

**Files:**
- Create: `extensions/vscode/src/syncProtocol.ts`
- Create: `extensions/vscode/test/syncProtocol.test.js`
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/test/core.test.js`

**Interfaces:**
- Produces: `SyncCommandOptions`, `SyncProgressEvent`, `SyncRunResult`, `buildSyncRunArgs`, `buildSyncStatusArgs`, `parseSyncProgressLine`, `parseSyncRunResult`, and `parseSyncStatusSummary`.
- Consumed by: Task 9 extension process integration.

- [ ] **Step 1: Write failing argument and parser tests**

```javascript
test("buildSyncRunArgs passes projects directly without resolving threads", () => {
  assert.deepEqual(
    buildSyncRunArgs({ syncDir: "/sync", projectKeys: ["repo-a"], threadIds: [], autoTransitions: false }),
    ["sync", "run", "--json", "--sync-dir", "/sync", "--no-auto-transitions", "--project-key", "repo-a"],
  );
});

test("parseSyncProgressLine accepts only typed phase events", () => {
  assert.deepEqual(parseSyncProgressLine('{"type":"sync_progress","phase":"pulling"}'), {
    type: "sync_progress",
    phase: "pulling",
  });
  assert.equal(parseSyncProgressLine("cache refreshed"), undefined);
  assert.equal(parseSyncProgressLine('{"type":"sync_progress","phase":"unknown"}'), undefined);
});
```

Add strict final-result tests for completed, conflict, and malformed payloads. Move the existing status-summary tests from `core.test.js` into this file, preserve their current state counts, and add coverage that plan-level `issues` are counted and their first actionable message is retained for the status UI.

- [ ] **Step 2: Run the new Node test and verify failure**

Run:

```bash
cd extensions/vscode && npm test
```

Expected: TypeScript build or test import fails because `syncProtocol` does not exist.

- [ ] **Step 3: Implement argument builders and strict parsers**

`buildSyncRunArgs` and `buildSyncStatusArgs` both append repeatable project keys and thread ids. Run begins `sync run --json`; status begins `sync status --json`. Add `--no-auto-transitions` only when requested.

`parseSyncRunResult` must require `outcome`, `counts`, `timings_ms`, `threads`, and `issues`. Do not coerce unknown outcomes. `parseSyncProgressLine` returns `undefined` for ordinary stderr diagnostics and malformed JSON.

- [ ] **Step 4: Route status parsing through the focused module without breaking current orchestration**

Move `parseSyncStatusSummary` and its type into `syncProtocol.ts`. Re-export the parser from `core.ts` temporarily so existing extension imports remain buildable in this checkpoint. Keep `SyncImportCommandOptions`, `buildSyncExportArgs`, `buildSyncImportArgs`, and the old sync argument appender until Task 9 switches the actual caller.

- [ ] **Step 5: Run extension tests**

Run:

```bash
cd extensions/vscode && npm test
```

Expected: build and all Node tests pass.

- [ ] **Step 6: Commit the protocol module**

```bash
git add extensions/vscode/src/syncProtocol.ts extensions/vscode/src/core.ts extensions/vscode/test/syncProtocol.test.js extensions/vscode/test/core.test.js
git commit -m "refactor: isolate the sync process protocol"
```

### Task 9: Run Sync Through Exactly One VS Code Child Process

**Files:**
- Create: `extensions/vscode/src/syncProcess.ts`
- Create: `extensions/vscode/test/syncProcess.test.js`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/test/core.test.js`

**Interfaces:**
- Consumes: Task 8 protocol builders/parsers and Node `spawn`.
- Produces: `runSyncProcess(options: RunSyncProcessOptions) -> Promise<SyncProcessCompletion>` with injected `spawnProcess` support for unit tests.
- Produces status phase `scanning` in addition to existing idle/waiting/pulling/pushing/conflict/issue states.

- [ ] **Step 1: Write a failing chunked-process test**

Build a fake child process with `EventEmitter` stdout/stderr and count invocations of the injected spawn function. Define these complete helpers in `syncProcess.test.js` before the test:

```javascript
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");

function completedResult(countOverrides = {}) {
  return {
    outcome: "completed",
    counts: {
      discovered: 1,
      selected: 1,
      remote: 0,
      pulled: 0,
      pushed: 1,
      unchanged: 0,
      conflicts: 0,
      issues: 0,
      ...countOverrides,
    },
    timings_ms: { discovery: 1, planning: 1, pull: 0, push: 1, index: 1, total: 4 },
    threads: [],
    pulled: [],
    pushed: ["thread-1"],
    issues: [],
  };
}

function fakeSyncChild({ stderrChunks, stdout, exitCode }) {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  queueMicrotask(() => {
    for (const chunk of stderrChunks) child.stderr.write(chunk);
    child.stdout.end(stdout);
    child.stderr.end();
    child.emit("close", exitCode);
  });
  return child;
}

test("runSyncProcess spawns once and streams chunked progress", async () => {
  const phases = [];
  const fake = fakeSyncChild({
    stderrChunks: ['{"type":"sync_', 'progress","phase":"pushing"}\n'],
    stdout: JSON.stringify(completedResult({ pushed: 1 })),
    exitCode: 0,
  });
  let spawnCount = 0;
  const completion = await runSyncProcess({
    executablePath: "/bin/codex-usage",
    args: ["sync", "run", "--json"],
    env: {},
    onProgress: (event) => phases.push(event.phase),
    onOutput: () => undefined,
    spawnProcess: () => {
      spawnCount += 1;
      return fake;
    },
  });
  assert.equal(spawnCount, 1);
  assert.deepEqual(phases, ["pushing"]);
  assert.equal(completion.result.outcome, "completed");
});
```

Add a test that exit code 2 with a valid conflict result resolves structurally, while a nonzero exit without valid result rejects with stderr details.

- [ ] **Step 2: Run the process test and verify failure**

Run:

```bash
cd extensions/vscode && npm test
```

Expected: module-not-found failure for `syncProcess`.

- [ ] **Step 3: Implement line-buffered stderr and structured completion**

Buffer partial stderr until newline, call `parseSyncProgressLine` for each complete line, flush one residual line on stream end, and still forward raw output to the Codex Usage channel. Parse stdout only after close. A valid final result is returned with the exit code so conflict/issue outcomes remain machine-readable.

- [ ] **Step 4: Replace extension orchestration**

In `runSyncNow`:

1. derive selectors directly from settings: project keys only for `allInProjects`, explicit ids only for `selectedConversations`;
2. set `scanning` before spawning;
3. invoke `runSyncProcess` exactly once with `buildSyncRunArgs`;
4. map progress events to `scanning`, `pulling`, or `pushing`;
5. map final `completed`, `conflict`, and `issue` outcomes to status and notifications.

For `showSyncStatus`, call the generic executable runner once with `buildSyncStatusArgs` and the same direct selectors. Delete `resolveSyncThreadIds` and `resolvedSyncOptions`; retain `buildThreadsArgs` only for setup pickers.

In this same step, delete `SyncImportCommandOptions`, `buildSyncExportArgs`, `buildSyncImportArgs`, and the old sync argument appender from `core.ts`; removing callers and definitions together keeps the TypeScript build green at the task boundary.

- [ ] **Step 5: Add the scanning status label and source guard**

Add `scanning` to `SYNC_STATUS_KIND_VALUES`, map it to `Scanning`, and update the existing status-label test. Add a test that reads `extension.ts` and asserts the removed resolver names and `buildSyncImportArgs`/`buildSyncExportArgs` no longer occur.

- [ ] **Step 6: Run the complete extension suite**

Run:

```bash
cd extensions/vscode && npm test
```

Expected: TypeScript compilation and all Node tests pass, including one-process and phase behavior.

- [ ] **Step 7: Commit extension integration**

```bash
git add extensions/vscode/src/syncProcess.ts extensions/vscode/src/extension.ts extensions/vscode/src/core.ts extensions/vscode/test/syncProcess.test.js extensions/vscode/test/core.test.js
git commit -m "feat: run extension sync in one process"
```

### Task 10: Record The Durable Contract And User Scenario

**Files:**
- Create: `docs/adr/0011-flat-single-process-sync.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`

**Interfaces:**
- Consumes: the approved design and implemented CLI/layout.
- Produces: public setup/cleanup guidance and a short ADR superseding only the version-1 layout and multi-command portions of ADRs 0007 and 0008.

- [ ] **Step 1: Write ADR 0011**

Use these sections: `Context`, `Decision`, `Alternatives Considered`, `Consequences`, and `Guardrails`. Record one flat JSONL per thread, one repairable central index, one process/plan, no migration code, optimistic validation, and preserved prefix-aware conflict semantics.

- [ ] **Step 2: Update both READMEs**

Replace `sync export` examples with `sync run`, show the exact version-2 tree, explain that existing users must empty old sync-folder contents themselves, and include:

> Continue a long-running Codex conversation on another computer when a normal handoff cannot complete because the conversation is too large. Sync transfers the original conversation JSONL without summarizing or repackaging its context.

State that selection never deletes remote conversations and that project mode discovers new matching conversations on later runs.

- [ ] **Step 3: Check durable-doc consistency**

Run:

```bash
rg -n "sync (import|export)|threads/<|manifest.json|index-entry.json" README.md extensions/vscode/README.md docs/adr/0011-flat-single-process-sync.md
```

Expected: no version-1 command or layout references appear except explicitly labeled historical context in ADR 0011.

- [ ] **Step 4: Commit docs and ADR**

```bash
git add docs/adr/0011-flat-single-process-sync.md docs/adr/README.md README.md extensions/vscode/README.md
git commit -m "docs: explain flat conversation sync"
```

### Task 11: Add Native Packaged Smoke Coverage And Prepare Version 0.1.33

**Files:**
- Create: `scripts/smoke-test-packaged-sync.py`
- Modify: `scripts/build-macos-arm64-exe.sh`
- Modify: `scripts/build-windows-exe.ps1`
- Modify: `tests/test_github_actions_workflow.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`

**Interfaces:**
- Consumes: the packaged `codex-usage` binary produced on each native runner.
- Produces: a standard-library smoke script that pushes one exact JSONL, pulls it into a second temporary Codex home, and validates the flat index/layout.
- Produces: coherent package version `0.1.33`; publishing and tagging remain explicit follow-up actions outside this implementation plan.

- [ ] **Step 1: Write failing workflow/build-script assertions**

Extend `tests/test_github_actions_workflow.py` to assert both native build scripts reference `smoke-test-packaged-sync.py`, and the workflow still runs Python and extension tests before packaging on `windows-2025` and `macos-26`.

- [ ] **Step 2: Run the workflow test and verify failure**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py -q
```

Expected: failures report that neither build script invokes the packaged-sync smoke test.

- [ ] **Step 3: Implement the cross-platform packaged smoke script**

The script accepts `--executable PATH`, creates source/target `CODEX_HOME` directories and a temporary sync folder, writes one minimal valid source JSONL plus `session_index.jsonl`, invokes `sync run --thread-id thread-1 --json` twice, and asserts:

```python
assert pushed["outcome"] == "completed"
assert pushed["counts"]["pushed"] == 1
assert remote_jsonl.read_bytes() == source_jsonl.read_bytes()
assert json.loads(sync_index.read_text(encoding="utf-8"))["format_version"] == 2
assert pulled["counts"]["pulled"] == 1
assert imported_jsonl.read_bytes() == source_jsonl.read_bytes()
assert not (sync_dir / "threads").exists()
```

Use only the standard library so the packaged binary is the component under test.

- [ ] **Step 4: Invoke smoke coverage from both native build scripts**

Keep the existing macOS `--help` check, add the equivalent check to the Windows script, then run the smoke script with each built executable. Preserve the current platform guard and PyInstaller one-file options.

- [ ] **Step 5: Bump release metadata to 0.1.33**

Run:

```bash
uv version 0.1.33
(cd extensions/vscode && npm version 0.1.33 --no-git-tag-version)
```

Add changelog entries covering flat one-file storage, one-process performance, large-task continuation, clean version-1 resync, and preserved conflict safety.

- [ ] **Step 6: Run complete source verification**

Run:

```bash
uv run pytest -q
(cd extensions/vscode && npm test)
```

Expected: all Python and extension tests pass.

- [ ] **Step 7: Build and smoke-test the local macOS package**

Run:

```bash
(cd extensions/vscode && npm run package:vsix:mac)
```

Expected: PyInstaller builds the Apple Silicon executable, the packaged-sync smoke script passes, and `output/releases/codex-usage-dashboard-darwin-arm64.vsix` exists.

- [ ] **Step 8: Verify version and diff integrity**

Run:

```bash
uv run python - <<'PY'
import json
import tomllib
from pathlib import Path

root = Path.cwd()
python_version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
extension_version = json.loads((root / "extensions/vscode/package.json").read_text())["version"]
lock_version = json.loads((root / "extensions/vscode/package-lock.json").read_text())["version"]
assert python_version == extension_version == lock_version == "0.1.33"
PY
git diff --check
git status --short
```

Expected: versions agree, no whitespace errors exist, and only intended implementation/release files are changed.

- [ ] **Step 9: Commit packaged verification and release metadata**

```bash
git add scripts/smoke-test-packaged-sync.py scripts/build-macos-arm64-exe.sh scripts/build-windows-exe.ps1 tests/test_github_actions_workflow.py pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json CHANGELOG.md extensions/vscode/CHANGELOG.md
git commit -m "chore: prepare 0.1.33 sync release"
```

## Final Verification Gate

Before requesting merge or push, run from the repository root:

```bash
uv run pytest -q
cd extensions/vscode && npm test && npm run package:vsix:mac
cd ../..
git diff --check
git status --short --branch
```

Expected:

- the complete Python suite passes;
- TypeScript builds and all extension tests pass;
- the packaged macOS arm64 sync round trip passes;
- the macOS VSIX exists under ignored `output/releases/`;
- no tracked generated binary, secret, `.env`, sync fixture, or user conversation JSONL is staged;
- the branch contains focused commits for package extraction, storage, inventory, planner, runner, CLI, TypeScript protocol, extension integration, docs/ADR, and release preparation.

After push, run the existing `Package and Publish VSIX` workflow with publishing disabled first. Its native Windows x64 and macOS arm64 jobs must both pass tests, packaged sync smoke coverage, and VSIX creation before any explicit publish run.
