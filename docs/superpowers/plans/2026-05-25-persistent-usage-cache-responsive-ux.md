# Persistent Usage Cache And Responsive UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent SQLite usage cache and visible loading states so range switches, project pickers, and sync setup feel responsive after the first scan.

**Architecture:** Keep parsing, transitions, aggregation, and reporting in Python. The VS Code extension continues to spawn the bundled executable, but passes an internal cache directory through `CODEX_USAGE_CACHE_DIR` and immediately shows loading status before long commands. Parsed usage rows are cached per JSONL file using path/size/mtime fingerprints; pricing remains computed at report time.

**Tech Stack:** Python 3.13, stdlib `sqlite3`, stdlib `json`, existing `pytest`, VS Code extension TypeScript, Node `child_process.spawn`, Node `node:test`.

---

## File Structure

- Create: `src/codex_usage/session_cache.py`
  - Owns SQLite schema, cache directory resolution, fingerprint checks, cache refresh, serialization/deserialization of parsed records, and cached transition rows.
- Create: `src/codex_usage/session_files.py`
  - Owns small shared helpers for reading `session_meta`, reading `session_index.jsonl`, resolving the owning sessions directory, and calculating session file sizes.
- Create: `src/codex_usage/sync_constants.py`
  - Owns sync-size constants shared by cache, thread listing, and sync without creating import cycles.
- Create: `src/codex_usage/threads.py`
  - Owns `ThreadInfo` and thread listing from cached session data. This keeps new thread-picker work out of the already-large `sync.py`.
- Modify: `src/codex_usage/parser.py`
  - Expose a `finalize_session_records(records_by_file)` function so cached per-file records still receive parent/subagent project identity inheritance exactly like direct parsing.
- Modify: `src/codex_usage/cli.py`
  - Route `summary`, `report`, `threads`, and `transitions suggest` through cached session data with no-cache fallback.
- Modify: `src/codex_usage/sync.py`
  - Re-export `ThreadInfo` and `list_threads` from `threads.py`, and remove the old in-file implementations.
- Modify: `extensions/vscode/src/core.ts`
  - Add cache env helpers and richer loading HTML copy.
- Modify: `extensions/vscode/src/extension.ts`
  - Pass `CODEX_USAGE_CACHE_DIR` to spawned CLI commands, show first-run/refresh loading UI immediately, add status bar loading labels, and refresh only once during sync setup.
- Modify: `extensions/vscode/test/core.test.js`
  - Cover cache env helpers and loading HTML copy.
- Create: `tests/test_session_cache.py`
  - Cover cache build/reuse/reparse/delete/schema/corrupt-file behavior.
- Modify: `tests/test_cli.py`, `tests/test_sync.py`
  - Add cache path smoke assertions and cached thread listing coverage.
- Modify: `README.md`, `extensions/vscode/README.md`, `CHANGELOG.md`
  - Document first-run cache behavior and bump beta version to `0.1.17`.
- Modify: `pyproject.toml`, `extensions/vscode/package.json`, `extensions/vscode/package-lock.json`
  - Bump package versions to `0.1.17`.

---

### Task 1: Parser Finalization Seam

**Files:**
- Modify: `src/codex_usage/parser.py`
- Test: `tests/test_parser_aggregation.py`

- [ ] **Step 1: Write the failing parser finalization test**

Add this test near the existing parent-thread identity tests in `tests/test_parser_aggregation.py`:

```python
def test_finalize_session_records_preserves_parent_identity_inheritance(tmp_path: Path) -> None:
    parent = tmp_path / "parent.jsonl"
    child = tmp_path / "child.jsonl"
    _write_jsonl(
        parent,
        [
            _session_meta(
                cwd="/repo/parent",
                repo="https://github.com/example/parent.git",
                session_id="parent-thread",
            ),
            _turn_context(model="gpt-5.5"),
            _token_count(total=100),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(
                cwd="/repo/child-without-git",
                session_id="child-thread",
                parent_thread_id="parent-thread",
            ),
            _turn_context(model="gpt-5.5"),
            _token_count(total=50),
        ],
    )

    from codex_usage.parser import finalize_session_records, parse_session_file

    finalized = finalize_session_records([parse_session_file(parent), parse_session_file(child)])

    child_record = next(record for record in finalized if record.session_id == "child-thread")
    assert child_record.project_key == "https://github.com/example/parent"
    assert child_record.project_label == "parent"
    assert child_record.git_repository_url == "https://github.com/example/parent.git"
    assert "/repo/child-without-git" in child_record.project_aliases
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
uv run pytest tests/test_parser_aggregation.py::test_finalize_session_records_preserves_parent_identity_inheritance -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `finalize_session_records` does not exist.

- [ ] **Step 3: Expose parser finalization**

In `src/codex_usage/parser.py`, replace the body of `parse_session_files` with a call to the new function:

```python
def parse_session_files(paths: Iterable[Path]) -> list[UsageRecord]:
    return finalize_session_records([parse_session_file(path) for path in paths])


def finalize_session_records(records_by_file: Iterable[list[UsageRecord]]) -> list[UsageRecord]:
    grouped = list(records_by_file)
    identity_by_session: dict[str, UsageRecord] = {}
    for file_records in grouped:
        for record in file_records:
            if record.git_repository_url:
                identity_by_session[record.session_id] = record

    records: list[UsageRecord] = []
    for file_records in grouped:
        for record in file_records:
            parent_identity = identity_by_session.get(record.parent_thread_id)
            if parent_identity is not None and not record.git_repository_url:
                records.append(_inherit_parent_project_identity(record, parent_identity))
            else:
                records.append(record)
    return records
```

- [ ] **Step 4: Verify parser tests pass**

Run:

```powershell
uv run pytest tests/test_parser_aggregation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/codex_usage/parser.py tests/test_parser_aggregation.py
git commit -m "refactor: expose parser finalization seam"
```

---

### Task 2: SQLite Session Cache

**Files:**
- Create: `src/codex_usage/session_cache.py`
- Create: `src/codex_usage/session_files.py`
- Create: `src/codex_usage/sync_constants.py`
- Test: `tests/test_session_cache.py`

- [ ] **Step 1: Write cache tests**

Create `tests/test_session_cache.py`:

```python
import json
import os
from pathlib import Path

import pytest

import codex_usage.session_cache as cache_module
from codex_usage.session_cache import (
    CACHE_DB_NAME,
    CACHE_SCHEMA_VERSION,
    load_cached_session_data,
    resolve_cache_dir,
)


def test_first_cache_build_parses_and_stores_records(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.files == [session_path]
    assert data.stats.files_parsed == 1
    assert data.stats.files_reused == 0
    assert data.records[0].session_id == "thread-1"
    assert data.records[0].usage.total_tokens == 100
    assert (cache_dir / CACHE_DB_NAME).is_file()


def test_unchanged_file_is_reused_without_reparse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    def fail_parse(_path: Path):
        raise AssertionError("unchanged file should be loaded from cache")

    monkeypatch.setattr(cache_module, "parse_session_file", fail_parse)
    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_reused == 1
    assert data.records[0].usage.total_tokens == 100


def test_changed_file_reparses_when_size_or_mtime_changes(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    os.utime(session_path, None)

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_parsed == 1
    assert [record.usage.total_tokens for record in data.records] == [100, 50]


def test_removed_file_deletes_cached_rows(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first = _write_session(sessions, "thread-1", "/repo/one", 100)
    _write_session(sessions, "thread-2", "/repo/two", 75)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    first.unlink()

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_removed == 1
    assert [record.session_id for record in data.records] == ["thread-2"]


def test_schema_version_mismatch_rebuilds_cache(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    db_path = cache_dir / CACHE_DB_NAME

    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute("update schema_meta set value = ? where key = 'schema_version'", ("old",))

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.rebuilt is True
    assert data.records[0].usage.total_tokens == 100
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("select value from schema_meta where key = 'schema_version'").fetchone()
    assert row == (str(CACHE_SCHEMA_VERSION),)


def test_corrupt_file_records_error_and_keeps_other_files(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/good", 100)
    bad = sessions / "2026" / "04" / "29" / "bad.jsonl"
    bad.write_bytes(b'{"type": "session_meta", "payload": {"id": "bad"}}\n\xff\xfe\n')
    cache_dir = tmp_path / "cache"

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert [record.session_id for record in data.records] == ["thread-1"]
    assert data.stats.file_errors == 1
    assert data.file_errors[str(bad)]


def test_resolve_cache_dir_prefers_internal_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_cache = tmp_path / "env-cache"
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(env_cache))

    assert resolve_cache_dir([tmp_path / "codex" / "sessions"]) == env_cache


def _write_session(sessions: Path, session_id: str, cwd: str, total: int) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-04-29T10:00:00Z", "cwd": cwd},
        },
        {"timestamp": "2026-04-29T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
        _token_count("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _append_token_count(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count(timestamp, total)))


def _token_count(timestamp: str, total: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total,
                }
            },
        },
    }
```

- [ ] **Step 2: Run cache tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_session_cache.py -q
```

Expected: FAIL because `codex_usage.session_cache` does not exist.

- [ ] **Step 3: Add shared session file helpers**

Create `src/codex_usage/sync_constants.py`:

```python
SYNC_METADATA_OVERHEAD_BYTES = 4096
```

Create `src/codex_usage/session_files.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codex_usage.models import SessionMetadata
from codex_usage.parser import parse_timestamp


def read_session_metadata(path: Path) -> SessionMetadata | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                obj = _parse_json_line(line)
                if obj is None or obj.get("type") != "session_meta":
                    continue
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
                return SessionMetadata(
                    session_id=str(payload.get("id") or path.stem),
                    file_path=path,
                    timestamp=parse_timestamp(payload.get("timestamp")) or parse_timestamp(obj.get("timestamp")),
                    cwd=str(payload.get("cwd") or ""),
                    originator=str(payload.get("originator") or ""),
                    source=str(payload.get("source") or ""),
                    cli_version=str(payload.get("cli_version") or ""),
                    model_provider=str(payload.get("model_provider") or ""),
                    forked_from_id=str(payload.get("forked_from_id") or ""),
                    parent_thread_id=_extract_parent_thread_id(payload),
                    memory_mode=str(payload.get("memory_mode") or ""),
                    has_base_instructions=payload.get("base_instructions") is not None,
                    git_repository_url=str(git.get("repository_url") or ""),
                    git_branch=str(git.get("branch") or ""),
                    git_commit_hash=str(git.get("commit_hash") or ""),
                )
    except (OSError, UnicodeDecodeError):
        return None
    return None


def load_all_index_entries(session_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for session_dir in session_dirs:
        index_path = codex_home_from_session_dir(session_dir) / "session_index.jsonl"
        for entry in _read_index_entries(index_path):
            thread_id = str(entry.get("id") or "")
            if not thread_id:
                continue
            existing = entries.get(thread_id)
            if existing is None or str(entry.get("updated_at") or "") >= str(existing.get("updated_at") or ""):
                entries[thread_id] = entry
    return entries


def owning_session_dir(path: Path, session_dirs: list[Path]) -> Path:
    resolved = path.resolve(strict=False)
    for session_dir in session_dirs:
        session_root = session_dir.resolve(strict=False)
        if resolved == session_root or session_root in resolved.parents:
            return session_dir
    return session_dirs[0] if session_dirs else path.parent


def codex_home_from_session_dir(session_dir: Path) -> Path:
    return session_dir.parent if session_dir.name == "sessions" else session_dir


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_index_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.is_file():
        return entries
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                obj = _parse_json_line(line)
                if obj is not None:
                    entries.append(obj)
    except (OSError, UnicodeDecodeError):
        return []
    return entries


def _parse_json_line(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _extract_parent_thread_id(payload: dict[str, Any]) -> str:
    source = payload.get("source")
    if not isinstance(source, dict):
        return ""
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return ""
    thread_spawn = subagent.get("thread_spawn")
    if not isinstance(thread_spawn, dict):
        return ""
    return str(thread_spawn.get("parent_thread_id") or "")
```

- [ ] **Step 4: Implement the cache module**

Create `src/codex_usage/session_cache.py` with these public dataclasses and functions. Use this exact public API so later tasks can depend on it:

```python
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.discovery import collect_jsonl_files
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import finalize_session_records, parse_session_file, parse_timestamp
from codex_usage.project_identity import resolve_project_identity
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_files import owning_session_dir, read_session_metadata
from codex_usage.sync_constants import SYNC_METADATA_OVERHEAD_BYTES

CACHE_DB_NAME = "usage-cache.sqlite3"
CACHE_SCHEMA_VERSION = 1
PARSER_CACHE_VERSION = 1
PROJECT_TRANSITION_CACHE_VERSION = 1


@dataclass(frozen=True)
class CacheStats:
    files_total: int = 0
    files_parsed: int = 0
    files_reused: int = 0
    files_removed: int = 0
    file_errors: int = 0
    rebuilt: bool = False


@dataclass(frozen=True)
class CachedFileSummary:
    file_path: Path
    session_dir: Path
    session_id: str
    cwd: str
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    git_repository_url: str
    git_branch: str
    memory_mode: str
    has_base_instructions: bool
    session_bytes: int
    estimated_sync_bytes: int
    error: str = ""


@dataclass(frozen=True)
class CachedSessionData:
    session_dirs: list[Path]
    files: list[Path]
    records: list[UsageRecord]
    file_summaries: dict[Path, CachedFileSummary]
    project_transitions: list[ProjectTransition]
    stats: CacheStats
    file_errors: dict[str, str]


def uncached_session_data(
    session_dirs: list[Path],
    files: list[Path],
    records: list[UsageRecord],
    project_transitions: list[ProjectTransition],
) -> CachedSessionData:
    return CachedSessionData(
        session_dirs=session_dirs,
        files=files,
        records=records,
        file_summaries={},
        project_transitions=project_transitions,
        stats=CacheStats(files_total=len(files)),
        file_errors={},
    )


def resolve_cache_dir(session_dirs: list[Path], cache_dir: Path | None = None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env_value = os.environ.get("CODEX_USAGE_CACHE_DIR", "").strip()
    if env_value:
        return Path(env_value)
    if os.environ.get("CODEX_HOME", "").strip():
        return Path(os.environ["CODEX_HOME"]).expanduser() / ".codex-usage-cache"
    if session_dirs:
        codex_home = session_dirs[0].parent
        return codex_home / ".codex-usage-cache"
    return Path.home() / ".codex" / ".codex-usage-cache"


def load_cached_session_data(
    session_dirs: list[Path],
    *,
    cache_dir: Path | None = None,
    auto_transitions: bool = True,
) -> CachedSessionData:
    resolved_cache_dir = resolve_cache_dir(session_dirs, cache_dir)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = resolved_cache_dir / CACHE_DB_NAME
    session_files = collect_jsonl_files(session_dirs)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rebuilt = _ensure_schema(connection)
        stats = _refresh_files(connection, session_dirs, session_files, rebuilt=rebuilt)
        records_by_file = _load_records_by_file(connection, session_files)
        records = finalize_session_records([records_by_file.get(path, []) for path in session_files])
        transitions = _refresh_or_load_transitions(connection, session_dirs, session_files, records, stats, auto_transitions)
        if auto_transitions:
            records = apply_project_transitions(records, transitions)
        summaries = _load_file_summaries(connection, session_files, session_dirs)
        errors = _load_file_errors(connection)
    return CachedSessionData(
        session_dirs=session_dirs,
        files=session_files,
        records=records,
        file_summaries=summaries,
        project_transitions=transitions,
        stats=stats,
        file_errors=errors,
    )
```

Continue the implementation with these required private helpers:

```python
def _ensure_schema(connection: sqlite3.Connection) -> bool:
    if _schema_matches(connection):
        return False
    _drop_cache_tables(connection)
    connection.executescript(
        """
        create table schema_meta (key text primary key, value text not null);
        create table files (
            path text primary key,
            session_dir text not null,
            size_bytes integer not null,
            mtime_ns integer not null,
            parsed_at text not null,
            session_id text,
            error text
        );
        create table usage_records (
            file_path text not null,
            record_index integer not null,
            timestamp text not null,
            session_id text not null,
            turn_id text,
            model text not null,
            effort text,
            collaboration_mode text,
            project_key text not null,
            project_label text not null,
            project_aliases_json text not null,
            cwd text,
            git_repository_url text,
            git_branch text,
            parent_thread_id text,
            input_tokens integer not null,
            cached_input_tokens integer not null,
            output_tokens integer not null,
            reasoning_output_tokens integer not null,
            total_tokens integer not null,
            primary key (file_path, record_index)
        );
        create table session_metadata (
            file_path text primary key,
            session_dir text not null,
            session_id text not null,
            cwd text,
            project_key text,
            project_label text,
            project_aliases_json text not null,
            git_repository_url text,
            git_branch text,
            memory_mode text,
            has_base_instructions integer not null,
            session_bytes integer not null,
            estimated_sync_bytes integer not null
        );
        create table project_transitions (
            source_key text not null,
            source_label text not null,
            target_key text not null,
            target_label text not null,
            effective_from text not null,
            confidence integer not null,
            evidence_json text not null,
            thread_ids_json text not null
        );
        """
    )
    connection.executemany(
        "insert into schema_meta (key, value) values (?, ?)",
        [
            ("schema_version", str(CACHE_SCHEMA_VERSION)),
            ("parser_version", str(PARSER_CACHE_VERSION)),
            ("project_transition_version", str(PROJECT_TRANSITION_CACHE_VERSION)),
        ],
    )
    connection.commit()
    return True
```

Implement serialization using existing model fields:

```python
def _insert_record(connection: sqlite3.Connection, file_path: Path, index: int, record: UsageRecord) -> None:
    usage = record.usage
    connection.execute(
        """
        insert into usage_records (
            file_path, record_index, timestamp, session_id, turn_id, model, effort,
            collaboration_mode, project_key, project_label, project_aliases_json,
            cwd, git_repository_url, git_branch, parent_thread_id,
            input_tokens, cached_input_tokens, output_tokens,
            reasoning_output_tokens, total_tokens
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(file_path),
            index,
            record.timestamp.isoformat(),
            record.session_id,
            record.turn_id,
            record.model,
            record.effort,
            record.collaboration_mode,
            record.project_key,
            record.project_label,
            json.dumps(list(record.project_aliases)),
            record.cwd,
            record.git_repository_url,
            record.git_branch,
            record.parent_thread_id,
            usage.input_tokens,
            usage.cached_input_tokens,
            usage.output_tokens,
            usage.reasoning_output_tokens,
            usage.total_tokens,
        ),
    )


def _row_to_record(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        timestamp=parse_timestamp(row["timestamp"]) or datetime.fromtimestamp(0, tz=UTC),
        usage=TokenUsage(
            input_tokens=int(row["input_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
            total_tokens=int(row["total_tokens"]),
        ),
        session_id=row["session_id"],
        file_path=Path(row["file_path"]),
        model=row["model"],
        turn_id=row["turn_id"] or "",
        effort=row["effort"] or "",
        collaboration_mode=row["collaboration_mode"] or "",
        project_key=row["project_key"],
        project_label=row["project_label"],
        project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
        cwd=row["cwd"] or "",
        git_repository_url=row["git_repository_url"] or "",
        git_branch=row["git_branch"] or "",
        parent_thread_id=row["parent_thread_id"] or "",
    )
```

The refresh helper must catch per-file exceptions and continue:

```python
def _refresh_one_file(connection: sqlite3.Connection, session_dirs: list[Path], path: Path) -> tuple[int, str]:
    _delete_file_rows(connection, path)
    stat = path.stat()
    try:
        records = parse_session_file(path)
        for index, record in enumerate(records):
            _insert_record(connection, path, index, record)
        _insert_file_summary(connection, session_dirs, path, records)
        error = ""
    except Exception as exc:
        records = []
        error = f"{type(exc).__name__}: {exc}"
    connection.execute(
        """
        insert or replace into files
            (path, session_dir, size_bytes, mtime_ns, parsed_at, session_id, error)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            str(owning_session_dir(path, session_dirs)),
            stat.st_size,
            stat.st_mtime_ns,
            datetime.now(UTC).isoformat(),
            records[0].session_id if records else path.stem,
            error,
        ),
    )
    return (len(records), error)
```

Use `_insert_file_summary` to store metadata plus the latest record identity for the thread picker:

```python
def _insert_file_summary(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    path: Path,
    records: list[UsageRecord],
) -> None:
    stat = path.stat()
    metadata = read_session_metadata(path)
    selected = records[-1] if records else None
    identity = None if selected is not None or metadata is None else resolve_project_identity(metadata)
    session_id = selected.session_id if selected else (metadata.session_id if metadata else path.stem)
    project_key = selected.project_key if selected else (identity.key if identity else "")
    project_label = selected.project_label if selected else (identity.label if identity else "")
    project_aliases = selected.project_aliases if selected else (identity.aliases if identity else ())
    connection.execute(
        """
        insert or replace into session_metadata (
            file_path, session_dir, session_id, cwd, project_key, project_label,
            project_aliases_json, git_repository_url, git_branch, memory_mode,
            has_base_instructions, session_bytes, estimated_sync_bytes
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            str(owning_session_dir(path, session_dirs)),
            session_id,
            selected.cwd if selected else (metadata.cwd if metadata else ""),
            project_key,
            project_label,
            json.dumps(list(project_aliases)),
            selected.git_repository_url if selected else (metadata.git_repository_url if metadata else ""),
            selected.git_branch if selected else (metadata.git_branch if metadata else ""),
            metadata.memory_mode if metadata else "",
            1 if metadata and metadata.has_base_instructions else 0,
            stat.st_size,
            stat.st_size + SYNC_METADATA_OVERHEAD_BYTES,
        ),
    )
```

Add these cache helpers in the same module:

```python
def _schema_matches(connection: sqlite3.Connection) -> bool:
    try:
        rows = connection.execute("select key, value from schema_meta").fetchall()
    except sqlite3.Error:
        return False
    values = {str(row["key"]): str(row["value"]) for row in rows}
    return values == {
        "schema_version": str(CACHE_SCHEMA_VERSION),
        "parser_version": str(PARSER_CACHE_VERSION),
        "project_transition_version": str(PROJECT_TRANSITION_CACHE_VERSION),
    }


def _drop_cache_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        drop table if exists project_transitions;
        drop table if exists session_metadata;
        drop table if exists usage_records;
        drop table if exists files;
        drop table if exists schema_meta;
        """
    )


def _refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    session_files: list[Path],
    *,
    rebuilt: bool,
) -> CacheStats:
    cached_rows = {
        Path(row["path"]): row
        for row in connection.execute("select path, size_bytes, mtime_ns from files").fetchall()
    }
    current_files = set(session_files)
    removed_files = [path for path in cached_rows if path not in current_files]
    for path in removed_files:
        _delete_file_rows(connection, path)

    parsed = 0
    reused = 0
    errors = 0
    for path in session_files:
        stat = path.stat()
        cached = cached_rows.get(path)
        if cached and int(cached["size_bytes"]) == stat.st_size and int(cached["mtime_ns"]) == stat.st_mtime_ns:
            reused += 1
            continue
        _record_count, error = _refresh_one_file(connection, session_dirs, path)
        parsed += 1
        if error:
            errors += 1
    connection.commit()
    return CacheStats(
        files_total=len(session_files),
        files_parsed=parsed,
        files_reused=reused,
        files_removed=len(removed_files),
        file_errors=errors,
        rebuilt=rebuilt,
    )


def _delete_file_rows(connection: sqlite3.Connection, path: Path) -> None:
    value = str(path)
    connection.execute("delete from usage_records where file_path = ?", (value,))
    connection.execute("delete from session_metadata where file_path = ?", (value,))
    connection.execute("delete from files where path = ?", (value,))


def _load_records_by_file(connection: sqlite3.Connection, session_files: list[Path]) -> dict[Path, list[UsageRecord]]:
    if not session_files:
        return {}
    rows = connection.execute(
        "select * from usage_records order by file_path, record_index"
    ).fetchall()
    selected = {str(path) for path in session_files}
    records_by_file: dict[Path, list[UsageRecord]] = {}
    for row in rows:
        if row["file_path"] not in selected:
            continue
        records_by_file.setdefault(Path(row["file_path"]), []).append(_row_to_record(row))
    return records_by_file


def _refresh_or_load_transitions(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    session_files: list[Path],
    records: list[UsageRecord],
    stats: CacheStats,
    auto_transitions: bool,
) -> list[ProjectTransition]:
    if not auto_transitions:
        return []
    if stats.rebuilt or stats.files_parsed or stats.files_removed:
        observations = collect_repo_path_observations(session_dirs, session_files)
        transitions = infer_project_transitions(records, observations)
        connection.execute("delete from project_transitions")
        for transition in transitions:
            connection.execute(
                """
                insert into project_transitions (
                    source_key, source_label, target_key, target_label,
                    effective_from, confidence, evidence_json, thread_ids_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transition.source_key,
                    transition.source_label,
                    transition.target_key,
                    transition.target_label,
                    transition.effective_from.isoformat(),
                    transition.confidence,
                    json.dumps(list(transition.evidence)),
                    json.dumps(list(transition.thread_ids)),
                ),
            )
        connection.commit()
        return transitions
    return _load_transitions(connection)


def _load_transitions(connection: sqlite3.Connection) -> list[ProjectTransition]:
    transitions: list[ProjectTransition] = []
    for row in connection.execute("select * from project_transitions order by effective_from, source_key, target_key"):
        timestamp = parse_timestamp(row["effective_from"])
        if timestamp is None:
            continue
        transitions.append(
            ProjectTransition(
                source_key=row["source_key"],
                source_label=row["source_label"],
                target_key=row["target_key"],
                target_label=row["target_label"],
                effective_from=timestamp,
                confidence=int(row["confidence"]),
                evidence=tuple(json.loads(row["evidence_json"] or "[]")),
                thread_ids=tuple(json.loads(row["thread_ids_json"] or "[]")),
            )
        )
    return transitions


def _load_file_summaries(
    connection: sqlite3.Connection,
    session_files: list[Path],
    session_dirs: list[Path],
) -> dict[Path, CachedFileSummary]:
    selected = {str(path) for path in session_files}
    summaries: dict[Path, CachedFileSummary] = {}
    for row in connection.execute("select * from session_metadata"):
        if row["file_path"] not in selected:
            continue
        path = Path(row["file_path"])
        summaries[path] = CachedFileSummary(
            file_path=path,
            session_dir=Path(row["session_dir"]) if row["session_dir"] else owning_session_dir(path, session_dirs),
            session_id=row["session_id"],
            cwd=row["cwd"] or "",
            project_key=row["project_key"] or "",
            project_label=row["project_label"] or "",
            project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
            git_repository_url=row["git_repository_url"] or "",
            git_branch=row["git_branch"] or "",
            memory_mode=row["memory_mode"] or "",
            has_base_instructions=bool(row["has_base_instructions"]),
            session_bytes=int(row["session_bytes"]),
            estimated_sync_bytes=int(row["estimated_sync_bytes"]),
        )
    return summaries


def _load_file_errors(connection: sqlite3.Connection) -> dict[str, str]:
    errors: dict[str, str] = {}
    for row in connection.execute("select path, error from files where error is not null and error != ''"):
        errors[str(row["path"])] = str(row["error"])
    return errors
```

- [ ] **Step 5: Verify cache tests pass**

Run:

```powershell
uv run pytest tests/test_session_cache.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/codex_usage/session_cache.py src/codex_usage/session_files.py src/codex_usage/sync_constants.py tests/test_session_cache.py
git commit -m "feat: add persistent session cache"
```

---

### Task 3: CLI Cache Integration

**Files:**
- Modify: `src/codex_usage/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add CLI cache smoke tests**

Append these tests to `tests/test_cli.py`:

```python
def test_cli_uses_internal_cache_dir_env_var(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "extension-cache"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "thread-1.jsonl", "thread-1", "/repo/first", 100)

    result = _run_cli(
        ["summary", "--range", "all", "--by", "project", "--json"],
        env={"CODEX_HOME": str(codex_home), "CODEX_USAGE_CACHE_DIR": str(cache_dir)},
    )

    payload = json.loads(result.stdout)
    assert payload["total"]["usage"]["total_tokens"] == 100
    assert (cache_dir / "usage-cache.sqlite3").is_file()


def test_cli_cache_reuses_records_after_first_scan(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "thread-1.jsonl", "thread-1", "/repo/first", 100)
    env = {"CODEX_HOME": str(codex_home), "CODEX_USAGE_CACHE_DIR": str(cache_dir)}

    first = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)
    second = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)

    assert json.loads(first.stdout)["total"]["usage"] == json.loads(second.stdout)["total"]["usage"]
```

- [ ] **Step 2: Run the new CLI tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_cli.py::test_cli_uses_internal_cache_dir_env_var tests/test_cli.py::test_cli_cache_reuses_records_after_first_scan -q
```

Expected: FAIL because `cli.py` still uses direct parsing.

- [ ] **Step 3: Route context loading through cache with fallback**

In `src/codex_usage/cli.py`, import the cache API:

```python
from codex_usage.session_cache import CachedSessionData, load_cached_session_data, uncached_session_data
```

Replace direct parsing in `_load_context` with:

```python
def _load_context(args: argparse.Namespace) -> _Context:
    settings = get_settings()
    timezone = resolve_timezone(args.timezone or settings.timezone)
    session_dirs = find_session_dirs()
    auto_transitions = _auto_project_transitions_enabled(args, settings)
    data = _load_session_data(session_dirs, auto_transitions=auto_transitions)
    project_keys = _normalize_project_keys(args.project_key)
    range_records = filter_records_by_range(data.records, args.range_name, timezone)
    filtered_records = filter_records_by_project_keys(range_records, project_keys)
    filtered_transitions = _filter_project_transitions(data.project_transitions, filtered_records)
    return _Context(
        session_dirs=session_dirs,
        files=data.files,
        records=filtered_records,
        timezone=timezone,
        project_keys=project_keys,
        project_transitions=filtered_transitions,
    )


def _load_session_data(session_dirs: list[Path], *, auto_transitions: bool) -> CachedSessionData:
    try:
        return load_cached_session_data(session_dirs, auto_transitions=auto_transitions)
    except Exception as exc:
        print(f"codex-usage: cache unavailable, falling back to direct parse: {exc}", file=sys.stderr)
        files = collect_jsonl_files(session_dirs)
        records = parse_session_files(files)
        project_transitions: list[ProjectTransition] = []
        if auto_transitions:
            observations = collect_repo_path_observations(session_dirs, files)
            project_transitions = infer_project_transitions(records, observations)
            records = apply_project_transitions(records, project_transitions)
        return uncached_session_data(
            session_dirs=session_dirs,
            files=files,
            records=records,
            project_transitions=project_transitions,
        )
```

- [ ] **Step 4: Update transition suggestion to use cached transitions**

Change `handle_transitions_suggest`:

```python
def handle_transitions_suggest(args: argparse.Namespace) -> int:
    session_dirs = _existing_session_dirs()
    data = _load_session_data(session_dirs, auto_transitions=True)

    if args.json:
        print_json(
            {
                "sessions_dirs": [str(path) for path in session_dirs],
                "files_scanned": len(data.files),
                "observations_count": 0,
                "project_transitions": _transition_dicts(data.project_transitions),
            }
        )
    else:
        for transition in data.project_transitions:
            print(
                f"{transition.source_label} -> {transition.target_label} @ "
                f"{transition.effective_from.isoformat()} {transition.confidence}"
            )
    return 0
```

- [ ] **Step 5: Verify CLI tests pass**

Run:

```powershell
uv run pytest tests/test_cli.py tests/test_cli_transitions.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/codex_usage/cli.py src/codex_usage/session_cache.py tests/test_cli.py
git commit -m "feat: use cache for CLI summaries and reports"
```

---

### Task 4: Cached Thread Listing And Sync Module Split

**Files:**
- Create: `src/codex_usage/threads.py`
- Modify: `src/codex_usage/sync.py`
- Modify: `src/codex_usage/session_files.py`
- Modify: `src/codex_usage/cli.py`
- Test: `tests/test_sync.py`, `tests/test_cli.py`

- [ ] **Step 1: Add cached thread-listing tests**

Append this test to `tests/test_sync.py`:

```python
def test_list_threads_can_use_cached_session_data(tmp_path: Path) -> None:
    from codex_usage.session_cache import load_cached_session_data
    from codex_usage.threads import list_threads_from_cached_data

    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    project = tmp_path / "repo"
    _write_git_config(project, "https://github.com/example/demo.git")
    session_path = _write_session(sessions, "thread-1", project, total=120)
    _write_index(codex_home, {"id": "thread-1", "thread_name": "Demo thread", "updated_at": "2026-04-29T10:05:00Z"})
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache", auto_transitions=True)

    threads = list_threads_from_cached_data(data, project_keys=["https://github.com/example/demo"])

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].title == "Demo thread"
    assert threads[0].project_key == "https://github.com/example/demo"
    assert threads[0].session_path == session_path
    assert threads[0].estimated_sync_bytes >= threads[0].session_bytes
```

Add this CLI assertion to `test_cli_threads_and_sync_commands` in `tests/test_cli.py` after `threads_payload` is loaded:

```python
    assert "estimated_sync_bytes" in threads_payload["threads"][0]
```

- [ ] **Step 2: Run thread tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_sync.py::test_list_threads_can_use_cached_session_data tests/test_cli.py::test_cli_threads_and_sync_commands -q
```

Expected: FAIL because `codex_usage.threads` does not exist.

- [ ] **Step 3: Create `threads.py`**

Move `ThreadInfo`, `_thread_identity`, `_normalize_project_filter_keys`, timestamp sorting helpers, and the thread-listing loop from `src/codex_usage/sync.py` into `src/codex_usage/threads.py`. The duplicated metadata and index helpers should be replaced by the shared functions already created in `session_files.py`. Add this cached entry point:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codex_usage.aggregation import filter_records_by_project_keys, summarize_records
from codex_usage.models import SessionMetadata, UsageRecord
from codex_usage.session_cache import CachedFileSummary, CachedSessionData
from codex_usage.session_files import load_all_index_entries


@dataclass(frozen=True)
class ThreadInfo:
    thread_id: str
    title: str
    updated_at: str
    session_path: Path
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    total_tokens: int
    session_bytes: int
    estimated_sync_bytes: int
    memory_mode: str = ""
    has_base_instructions: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "session_path": str(self.session_path),
            "project_key": self.project_key,
            "project_label": self.project_label,
            "project_aliases": list(self.project_aliases),
            "total_tokens": self.total_tokens,
            "session_bytes": self.session_bytes,
            "estimated_sync_bytes": self.estimated_sync_bytes,
            "memory_mode": self.memory_mode,
            "has_base_instructions": self.has_base_instructions,
        }
```

Implement `list_threads_from_cached_data` with current index entries and cached records:

```python
def list_threads_from_cached_data(
    data: CachedSessionData,
    project_keys: list[str] | None = None,
) -> list[ThreadInfo]:
    index_entries = load_all_index_entries(data.session_dirs)
    selected_project_keys = _normalize_project_filter_keys(project_keys)
    records_by_path: dict[Path, list[UsageRecord]] = {}
    for record in data.records:
        records_by_path.setdefault(record.file_path, []).append(record)

    threads: dict[str, ThreadInfo] = {}
    for path in data.files:
        summary = data.file_summaries.get(path)
        if summary is None:
            continue
        records = records_by_path.get(path, [])
        if selected_project_keys and not filter_records_by_project_keys(records, selected_project_keys):
            aliases = {summary.project_key, *summary.project_aliases}
            if not aliases.intersection(selected_project_keys):
                continue
        thread = _thread_from_summary(summary, records, index_entries.get(summary.session_id, {}))
        threads[thread.thread_id] = thread
    return sorted(threads.values(), key=lambda item: item.updated_at, reverse=True)


def _thread_from_summary(
    summary: CachedFileSummary,
    records: list[UsageRecord],
    index_entry: dict[str, object],
) -> ThreadInfo:
    token_total = summarize_records(records).usage.total_tokens if records else 0
    title = str(index_entry.get("thread_name") or index_entry.get("title") or summary.session_id)
    updated_at = str(index_entry.get("updated_at") or _latest_record_timestamp(records) or "")
    return ThreadInfo(
        thread_id=summary.session_id,
        title=title,
        updated_at=updated_at,
        session_path=summary.file_path,
        project_key=summary.project_key,
        project_label=summary.project_label,
        project_aliases=summary.project_aliases,
        total_tokens=token_total,
        session_bytes=summary.session_bytes,
        estimated_sync_bytes=summary.estimated_sync_bytes,
        memory_mode=summary.memory_mode,
        has_base_instructions=summary.has_base_instructions,
    )
```

- [ ] **Step 4: Keep sync imports backward-compatible**

In `src/codex_usage/sync.py`, remove the old `ThreadInfo` class, `list_threads` function, duplicated session metadata/index helpers that now live in `session_files.py`, and the local `SYNC_METADATA_OVERHEAD_BYTES` constant. Then add:

```python
from codex_usage.session_files import codex_home_from_session_dir, file_size, load_all_index_entries, owning_session_dir
from codex_usage.threads import ThreadInfo, list_threads
from codex_usage.sync_constants import SYNC_METADATA_OVERHEAD_BYTES
```

Replace old helper calls with the shared names:

```python
_codex_home_from_session_dir(...) -> codex_home_from_session_dir(...)
_file_size(...) -> file_size(...)
_load_all_index_entries(...) -> load_all_index_entries(...)
_owning_session_dir(...) -> owning_session_dir(...)
```

- [ ] **Step 5: Use cached threads in CLI**

In `src/codex_usage/cli.py`, change imports:

```python
from codex_usage.sync import export_threads, import_threads, sync_status
from codex_usage.threads import list_threads_from_cached_data
```

Change `handle_threads`:

```python
def handle_threads(args: argparse.Namespace) -> int:
    settings = get_settings()
    session_dirs = find_session_dirs()
    project_keys = _normalize_project_keys(args.project_key)
    data = _load_session_data(
        session_dirs,
        auto_transitions=_auto_project_transitions_enabled(args, settings),
    )
    threads = list_threads_from_cached_data(data, project_keys=project_keys)
    payload = {"threads": [thread.to_dict() for thread in threads], "project_keys": project_keys}
    if args.json:
        print_json(payload)
    else:
        for thread in threads:
            print(f"{thread.thread_id}\t{thread.title}\t{thread.project_label}\t{thread.updated_at}")
    return 0
```

- [ ] **Step 6: Verify sync tests pass**

Run:

```powershell
uv run pytest tests/test_sync.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/codex_usage/threads.py src/codex_usage/sync.py src/codex_usage/cli.py tests/test_sync.py tests/test_cli.py
git commit -m "refactor: list threads from cached session data"
```

---

### Task 5: VS Code Cache Env And Loading States

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/src/extension.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add core tests for cache env and loading copy**

In `extensions/vscode/test/core.test.js`, add imports:

```js
  buildCodexUsageEnv,
  cacheDbPath,
```

Add tests:

```js
test("buildCodexUsageEnv passes internal cache directory without removing process env", () => {
  const env = buildCodexUsageEnv("C:/global-storage", { PATH: "C:/bin", CODEX_HOME: "C:/codex" });

  assert.equal(env.PATH, "C:/bin");
  assert.equal(env.CODEX_HOME, "C:/codex");
  assert.equal(env.CODEX_USAGE_CACHE_DIR, path.join("C:/global-storage", "cache"));
});

test("cacheDbPath points at the Python cache database under extension storage", () => {
  assert.equal(cacheDbPath("C:/global-storage"), path.join("C:/global-storage", "cache", "usage-cache.sqlite3"));
});

test("renderLoadingHtml supports first-run and refresh copy without scripts", () => {
  const initializing = renderLoadingHtml("Initializing Codex usage cache. This can take a few seconds the first time.");
  const refreshing = renderLoadingHtml("Refreshing Codex usage...");

  assert.match(initializing, /Initializing Codex usage cache/);
  assert.match(refreshing, /Refreshing Codex usage/);
  assert.doesNotMatch(initializing, /<script/i);
  assert.doesNotMatch(refreshing, /<script/i);
});
```

- [ ] **Step 2: Run core tests and verify they fail**

Run:

```powershell
Push-Location extensions/vscode; npm test; Pop-Location
```

Expected: FAIL because cache helpers are missing or `renderLoadingHtml` does not accept custom copy.

- [ ] **Step 3: Add cache helpers to `core.ts`**

In `extensions/vscode/src/core.ts`, export:

```ts
export function cacheDirPath(globalStoragePath: string): string {
  return path.join(globalStoragePath, "cache");
}

export function cacheDbPath(globalStoragePath: string): string {
  return path.join(cacheDirPath(globalStoragePath), "usage-cache.sqlite3");
}

export function buildCodexUsageEnv(globalStoragePath: string, baseEnv: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  return {
    ...baseEnv,
    CODEX_USAGE_CACHE_DIR: cacheDirPath(globalStoragePath),
  };
}
```

Update `renderLoadingHtml` signature:

```ts
export function renderLoadingHtml(message = "Loading Codex usage..."): string {
  const escaped = escapeHtml(message);
  return `<!doctype html>
<html data-codex-theme="auto">
<head><meta charset="utf-8"><title>Codex Usage</title></head>
<body>
  <main class="report-shell">
    <section class="notice loading" role="status" aria-live="polite">${escaped}</section>
  </main>
</body>
</html>`;
}
```

- [ ] **Step 4: Wire cache env and webview loading in `extension.ts`**

Import the new helpers:

```ts
  buildCodexUsageEnv,
  cacheDbPath,
```

Change `runCodexUsage`:

```ts
function runCodexUsage(
  executablePath: string,
  args: string[],
  env: NodeJS.ProcessEnv = process.env,
): Promise<{ stdout: string; stderr: string }> {
  output.appendLine(`> ${executablePath} ${args.join(" ")}`);
  return new Promise((resolve, reject) => {
    const child = spawn(executablePath, args, {
      shell: false,
      windowsHide: true,
      env,
    });
```

Add loading helpers:

```ts
type UsageLoadingKind = "initializing" | "refreshing" | "projects" | "syncProjects" | "syncThreads";

function usageLoadingMessage(kind: UsageLoadingKind): string {
  if (kind === "initializing") {
    return "Initializing Codex usage cache. This can take a few seconds the first time.";
  }
  if (kind === "projects") {
    return "Loading Codex projects...";
  }
  if (kind === "syncProjects") {
    return "Loading sync projects...";
  }
  if (kind === "syncThreads") {
    return "Loading conversations...";
  }
  return "Refreshing Codex usage...";
}

async function dashboardLoadingKind(context: vscode.ExtensionContext): Promise<UsageLoadingKind> {
  try {
    await fs.access(cacheDbPath(context.globalStorageUri.fsPath));
    return "refreshing";
  } catch {
    return "initializing";
  }
}

function setDashboardLoading(
  context: vscode.ExtensionContext,
  targetPanel: vscode.WebviewPanel,
  kind: UsageLoadingKind,
): void {
  const settings = readSettings(context);
  targetPanel.webview.html = renderWebviewHtml(
    renderLoadingHtml(usageLoadingMessage(kind)),
    targetPanel.webview,
    settings,
    extensionVersionLabel(context.extension.packageJSON),
  );
}

function setUsageStatus(context: vscode.ExtensionContext, label: string): void {
  statusItem.text = label;
  statusItem.tooltip = label;
}
```

Use them in `refreshDashboard`:

```ts
async function refreshDashboard(context: vscode.ExtensionContext, targetPanel: vscode.WebviewPanel): Promise<void> {
  const settings = readSettings(context);
  const reportPath = path.join(context.globalStorageUri.fsPath, "report.html");
  const loadingKind = await dashboardLoadingKind(context);
  setDashboardLoading(context, targetPanel, loadingKind);
  setUsageStatus(context, loadingKind === "initializing" ? "Codex Usage: Initializing" : "Codex Usage: Loading");

  try {
    const executablePath = await resolveBundledExecutable(context);
    await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const args = buildReportArgs({
      range: settings.range,
      outputPath: reportPath,
      projectKeys: settings.projectKeys,
      theme: settings.theme,
      projectTransitions: settings.projectTransitions,
    });
    await runCodexUsage(executablePath, args, env);
    const reportHtml = await fs.readFile(reportPath, "utf8");
    targetPanel.webview.html = renderWebviewHtml(reportHtml, targetPanel.webview, settings, extensionVersionLabel(context.extension.packageJSON));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    targetPanel.webview.html = renderWebviewHtml(
      renderErrorHtml(`${message}\n\nCheck the Codex Usage output channel for details.`),
      targetPanel.webview,
      settings,
      extensionVersionLabel(context.extension.packageJSON),
    );
    void vscode.window.showErrorMessage(`Codex Usage failed: ${message}`);
  } finally {
    updateStatusItem(readSettings(context));
  }
}
```

Pass the same env to summary/thread commands:

```ts
const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
const result = await runCodexUsage(executablePath, buildSummaryArgs({ range: settings.range, projectTransitions: settings.projectTransitions }), env);
```

- [ ] **Step 5: Verify TS tests pass**

Run:

```powershell
Push-Location extensions/vscode; npm test; Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add extensions/vscode/src/core.ts extensions/vscode/src/extension.ts extensions/vscode/test/core.test.js
git commit -m "feat: show responsive cache loading states"
```

---

### Task 6: Sync Setup Responsiveness

**Files:**
- Modify: `extensions/vscode/src/extension.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add pure helper tests for refresh policy**

In `extensions/vscode/src/core.ts`, add:

```ts
export type SyncSetupStepOptions = {
  refreshDashboard?: boolean;
};

export function shouldRefreshAfterSyncSetupStep(options: SyncSetupStepOptions | undefined): boolean {
  return options?.refreshDashboard !== false;
}
```

In `extensions/vscode/test/core.test.js`, import `shouldRefreshAfterSyncSetupStep` and add:

```js
test("sync setup step refresh policy defaults to refresh and can be suppressed", () => {
  assert.equal(shouldRefreshAfterSyncSetupStep(undefined), true);
  assert.equal(shouldRefreshAfterSyncSetupStep({}), true);
  assert.equal(shouldRefreshAfterSyncSetupStep({ refreshDashboard: false }), false);
});
```

- [ ] **Step 2: Run TS tests and verify they fail before export/import is wired**

Run:

```powershell
Push-Location extensions/vscode; npm test; Pop-Location
```

Expected: FAIL until `shouldRefreshAfterSyncSetupStep` is exported and imported.

- [ ] **Step 3: Add optional refresh suppression to sync pickers**

In `extensions/vscode/src/extension.ts`, import `shouldRefreshAfterSyncSetupStep`.

Change function signatures:

```ts
async function selectSyncProjectSettings(
  context: vscode.ExtensionContext,
  options: { refreshDashboard?: boolean } = {},
): Promise<boolean> {
```

```ts
async function selectSyncThreadSettings(
  context: vscode.ExtensionContext,
  options: { refreshDashboard?: boolean } = {},
): Promise<boolean> {
```

Wrap the existing refresh blocks:

```ts
if (panel && shouldRefreshAfterSyncSetupStep(options)) {
  await refreshDashboard(context, panel);
}
```

Update `configureSync`:

```ts
const selectedProjects = await selectSyncProjectSettings(context, { refreshDashboard: false });
if (!selectedProjects && readSettings(context).sync.projectKeys.length === 0) {
  updateStatusItem(readSettings(context));
  configureSyncWatcher(context);
  if (panel) {
    await refreshDashboard(context, panel);
  }
  return;
}
await selectSyncThreadSettings(context, { refreshDashboard: false });
updateStatusItem(readSettings(context));
configureSyncWatcher(context);
if (panel) {
  await refreshDashboard(context, panel);
}
```

Use status labels around slow sync picker commands:

```ts
setUsageStatus(context, "Codex Usage: Loading Sync Projects");
try {
  // existing project loading
} finally {
  updateStatusItem(readSettings(context));
}
```

```ts
setUsageStatus(context, "Codex Usage: Loading Conversations");
try {
  // existing conversation loading
} finally {
  updateStatusItem(readSettings(context));
}
```

- [ ] **Step 4: Verify TS tests pass**

Run:

```powershell
Push-Location extensions/vscode; npm test; Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add extensions/vscode/src/core.ts extensions/vscode/src/extension.ts extensions/vscode/test/core.test.js
git commit -m "perf: refresh dashboard once during sync setup"
```

---

### Task 7: Documentation And Version Bump

**Files:**
- Modify: `pyproject.toml`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump Python and extension versions**

Set:

```toml
[project]
version = "0.1.17"
```

Set in `extensions/vscode/package.json`:

```json
"version": "0.1.17"
```

Run npm install to sync the lockfile:

```powershell
Push-Location extensions/vscode; npm install; Pop-Location
```

Expected: `extensions/vscode/package-lock.json` updates to `0.1.17`.

- [ ] **Step 2: Update docs**

Add this paragraph to the root `README.md` performance or usage section:

```markdown
### Performance Cache

The Windows VS Code beta stores a local SQLite cache under VS Code global extension storage. The first dashboard open may say "Initializing Codex usage cache" and take a few seconds while existing Codex JSONL files are parsed. Later range switches and project pickers reuse unchanged parsed rows and should usually feel much faster. The cache is local only, can be rebuilt automatically after schema changes, and does not change pricing semantics because costs are still calculated from checked-in effective-dated rates at report time.
```

Add this paragraph to `extensions/vscode/README.md`:

```markdown
## First Run And Cache

On first open, the dashboard may show "Initializing Codex usage cache. This can take a few seconds the first time." The extension passes an internal cache folder to the bundled Python CLI and stores parsed usage rows in local SQLite under VS Code global extension storage. No cache setting is exposed in VS Code Settings; deleting the extension storage folder simply causes the cache to rebuild.
```

Add a `0.1.17` entry to `CHANGELOG.md`:

```markdown
## 0.1.17

- Added a persistent local SQLite usage cache for faster dashboard refreshes, project pickers, and sync setup.
- Added clearer first-run and refresh loading messages in the dashboard and status bar.
- Reduced sync setup churn by refreshing the dashboard once after folder/project/conversation selection finishes.
```

- [ ] **Step 3: Commit**

```powershell
git add pyproject.toml extensions/vscode/package.json extensions/vscode/package-lock.json README.md extensions/vscode/README.md CHANGELOG.md
git commit -m "docs: document cache-backed responsive UX"
```

---

### Task 8: Full Verification, Bundle, And Local Main Merge

**Files:**
- No new files expected.

- [ ] **Step 1: Run Python tests**

Run:

```powershell
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run TypeScript tests and build**

Run:

```powershell
Push-Location extensions/vscode; npm test; npm run build; Pop-Location
```

Expected: all tests pass and TypeScript builds.

- [ ] **Step 3: Run local cache smoke**

Run:

```powershell
$env:CODEX_USAGE_CACHE_DIR = "$PWD\output\cache-smoke"
uv run codex-usage summary --range all --by project --json | Out-File -Encoding utf8 output\cache-summary-smoke.json
uv run codex-usage report --range 7d --output output\cache-report-smoke.html
Remove-Item Env:\CODEX_USAGE_CACHE_DIR
```

Expected:
- `output/cache-summary-smoke.json` contains valid JSON with `rows`.
- `output/cache-report-smoke.html` opens as the normal dashboard.
- `output/cache-smoke/usage-cache.sqlite3` exists.

- [ ] **Step 4: Rebuild bundled Windows executable and VSIX**

Run:

```powershell
Push-Location extensions/vscode
npm run package:vsix:win
Pop-Location
```

Expected:
- `output/codex-usage-dashboard-win32-x64.vsix` is rebuilt.
- VSIX contains `extension/bin/win32-x64/codex-usage.exe`.

- [ ] **Step 5: Inspect package contents**

Run:

```powershell
Push-Location extensions/vscode
npx vsce ls --tree
Pop-Location
```

Expected:
- Includes `extension/out/core.js`, `extension/out/extension.js`, `extension/media/icon.png`, `extension/bin/win32-x64/codex-usage.exe`.
- Does not include `src/*.ts`, `test/*.js`, `.vscode-test`, or local output files.

- [ ] **Step 6: Merge back to main locally if execution happened on a feature branch**

Run:

```powershell
git branch --show-current
```

If the output is not `main`, run:

```powershell
$branch = git branch --show-current
git switch main
git merge --no-ff $branch
```

Expected: feature work is integrated into local `main`.

- [ ] **Step 7: Final status**

Run:

```powershell
git status --short --branch
```

Expected: clean worktree on `main`, or only intentionally untracked generated output ignored by `.gitignore`.

---

## Self-Review

**Spec coverage:** This plan covers the Python SQLite cache, cache directory resolution through `CODEX_USAGE_CACHE_DIR`, fingerprint reuse, changed/deleted/corrupt file behavior, schema rebuild, cached summaries/reports/threads/transitions, no-cache fallback, responsive dashboard loading copy, status bar loading labels, project/sync picker progress, and one-refresh sync setup. It keeps pricing at aggregation/report time and does not add a daemon, service, TS parser, new public command names, or new VS Code cache setting.

**Placeholder scan:** No task uses `TBD`, `TODO`, "fill in details", or unspecified "add tests" language. Each task names files, gives concrete tests, commands, and expected results.

**Type consistency:** The plan consistently uses `CachedSessionData`, `CacheStats`, `CachedFileSummary`, `load_cached_session_data`, `resolve_cache_dir`, `list_threads_from_cached_data`, `buildCodexUsageEnv`, and `cacheDbPath` across Python and TypeScript tasks.
