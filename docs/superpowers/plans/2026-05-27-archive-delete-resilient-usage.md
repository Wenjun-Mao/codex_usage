# Archive And Delete Resilient Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make usage totals stable when Codex conversations are archived, moved, or deleted locally, while adding an observation path so we can verify real Codex delete behavior instead of guessing.

**Architecture:** Split Codex storage discovery from usage caching. Discovery finds active and archived session roots plus diagnostic storage folders; the cache stores usage by stable session-file identity instead of by path, marks missing files instead of deleting their usage rows, and deduplicates path moves so a session moved from `sessions` to `archived_sessions` is counted once.

**Tech Stack:** Python 3.13, SQLite cache, pytest, existing TypeScript VS Code wrapper, PyInstaller/VSIX packaging.

---

## Important Product Rules

- Archiving a Codex conversation must not remove historical usage from the dashboard.
- Deleting a Codex conversation after the new cache has seen it must not remove historical usage from the dashboard.
- A moved session file must not be double-counted if the same logical session appears under both `sessions` and `archived_sessions`.
- The sync thread picker must only offer conversations that still have local JSONL files. Retained missing cache rows are for historical usage, not sync export.
- The dashboard/report should disclose when archived files and retained missing files are included.
- The implementation must not assume Codex delete behavior. It must include a repeatable before/after storage snapshot command for the real manual experiment.

---

## File Structure

- Create `src/codex_usage/session_inventory.py`
  - Owns active/archived session root discovery, diagnostic storage snapshots, stable file-key derivation, and deduped current-file inventory.
- Modify `src/codex_usage/discovery.py`
  - Keep backward-compatible function names, but delegate to `session_inventory.py`.
  - Return both active `sessions` and `archived_sessions` roots when present.
  - Keep `default_session_dir()` pointing at writable active `sessions` for sync import.
- Modify `src/codex_usage/session_cache.py`
  - Move from path-primary cache identity to `file_key` primary identity.
  - Mark absent cached files as missing instead of deleting usage rows.
  - Deduplicate moved files by `file_key`.
  - Add stats for active, archived, current, and retained missing files.
- Modify `src/codex_usage/session_files.py`
  - Fix `load_all_index_entries()` so it calls `timestamp_key()` instead of the nonexistent `_timestamp_key()`.
- Modify `src/codex_usage/cli.py`
  - Add `codex-usage storage snapshot --json`.
  - Include archived/missing cache counts in summary/report metadata.
- Modify `src/codex_usage/reporting.py`
  - Add report header text for archived included and retained missing included.
  - Avoid scary warning styling for retained missing; it is expected historical accounting.
- Modify `src/codex_usage/reporting.py`
  - Add additive metadata fields: `storage_roots`, `files_archived`, `files_retained_missing`.
- Modify `src/codex_usage/threads.py`
  - Ensure thread listing excludes retained missing files.
- Modify tests:
  - `tests/test_discovery.py`
  - `tests/test_session_cache.py`
  - `tests/test_session_files.py`
  - `tests/test_cli.py`
  - `tests/test_reporting_html.py`
  - `tests/test_sync.py` if sync thread listing expectations need adjustment.
- Modify docs/version/package files:
  - `README.md`
  - `extensions/vscode/README.md`
  - `PRIVACY.md`
  - `CHANGELOG.md`
  - `pyproject.toml`
  - `uv.lock`
  - `extensions/vscode/package.json`
  - `extensions/vscode/package-lock.json`

---

### Task 1: Fix Index Entry Loading Helper

**Files:**
- Modify: `src/codex_usage/session_files.py`
- Test: create `tests/test_session_files.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_session_files.py`:

```python
import json
from pathlib import Path

from codex_usage.session_files import load_all_index_entries


def test_load_all_index_entries_keeps_newest_entry_per_thread(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    index = codex_home / "session_index.jsonl"
    rows = [
        {"id": "thread-1", "thread_name": "old", "updated_at": "2026-05-20T10:00:00Z"},
        {"id": "thread-1", "thread_name": "new", "updated_at": "2026-05-21T10:00:00Z"},
        {"id": "thread-2", "thread_name": "other", "updated_at": "2026-05-20T11:00:00Z"},
    ]
    index.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    entries = load_all_index_entries([sessions])

    assert entries["thread-1"]["thread_name"] == "new"
    assert entries["thread-2"]["thread_name"] == "other"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
uv run pytest tests/test_session_files.py::test_load_all_index_entries_keeps_newest_entry_per_thread -q
```

Expected: FAIL with `NameError: name '_timestamp_key' is not defined`.

- [ ] **Step 3: Fix the helper**

In `src/codex_usage/session_files.py`, change:

```python
if existing is None or _timestamp_key(str(entry.get("updated_at") or "")) >= _timestamp_key(
    str(existing.get("updated_at") or "")
):
```

to:

```python
if existing is None or timestamp_key(str(entry.get("updated_at") or "")) >= timestamp_key(
    str(existing.get("updated_at") or "")
):
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
uv run pytest tests/test_session_files.py::test_load_all_index_entries_keeps_newest_entry_per_thread -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/codex_usage/session_files.py tests/test_session_files.py
git commit -m "fix: load newest Codex index entries"
```

---

### Task 2: Add Session Inventory Layer

**Files:**
- Create: `src/codex_usage/session_inventory.py`
- Modify: `src/codex_usage/discovery.py`
- Test: `tests/test_discovery.py`

- [ ] **Step 1: Write failing discovery tests**

Append these tests to `tests/test_discovery.py`:

```python
def test_find_session_dirs_includes_archived_sessions(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    sessions.mkdir(parents=True)
    archived.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    found = find_session_dirs()

    assert found == [sessions, archived]


def test_find_session_dirs_allows_archived_only_for_historical_reports(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    archived = codex_home / "archived_sessions"
    archived.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    found = find_session_dirs()

    assert found == [archived]


def test_collect_jsonl_files_dedupes_active_and_archived_by_file_key(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active = _write_inventory_session(sessions, "thread-1", 100)
    _write_inventory_session(archived, "thread-1", 100)

    files = collect_jsonl_files([sessions, archived])

    assert files == [active]
```

Add this helper at the bottom of `tests/test_discovery.py`:

```python
def _write_inventory_session(root: Path, session_id: str, total: int) -> Path:
    day = root / "2026" / "05" / "27"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{session_id}.jsonl"
    rows = [
        {"timestamp": "2026-05-27T10:00:00Z", "type": "session_meta", "payload": {"id": session_id}},
        {
            "timestamp": "2026-05-27T10:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": total, "total_tokens": total}},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path
```

Also add `import json` at the top of `tests/test_discovery.py`.

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_discovery.py -q
```

Expected: FAIL because archived session roots and file-key dedupe do not exist yet.

- [ ] **Step 3: Create `session_inventory.py`**

Create `src/codex_usage/session_inventory.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from codex_usage.session_files import read_session_metadata


ACTIVE_SESSION_DIR_NAME = "sessions"
ARCHIVED_SESSION_DIR_NAME = "archived_sessions"


@dataclass(frozen=True)
class SessionFileInventoryEntry:
    file_key: str
    path: Path
    session_dir: Path
    storage_state: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class StorageRootSnapshot:
    path: Path
    storage_state: str
    exists: bool
    jsonl_count: int
    total_bytes: int


def candidate_session_dirs(
    *,
    codex_home: str | None = None,
    userprofile: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    for base in _candidate_codex_homes(codex_home=codex_home, userprofile=userprofile, home=home):
        candidates.append(base / ACTIVE_SESSION_DIR_NAME)
        candidates.append(base / ARCHIVED_SESSION_DIR_NAME)
    return _dedupe_paths(candidates)


def find_session_dirs() -> list[Path]:
    codex_home = os.getenv("CODEX_HOME")
    candidates = candidate_session_dirs(codex_home=codex_home, userprofile=os.getenv("USERPROFILE"))
    existing = [path for path in candidates if path.is_dir()]
    if existing:
        return existing
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No Codex sessions directory found. Checked: {checked}")


def default_session_dir() -> Path:
    codex_home = os.getenv("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / ACTIVE_SESSION_DIR_NAME
    userprofile = os.getenv("USERPROFILE", "").strip()
    if userprofile:
        return Path(userprofile).expanduser() / ".codex" / ACTIVE_SESSION_DIR_NAME
    return Path.home() / ".codex" / ACTIVE_SESSION_DIR_NAME


def collect_session_file_inventory(session_dirs: list[Path]) -> list[SessionFileInventoryEntry]:
    selected: dict[str, SessionFileInventoryEntry] = {}
    for session_dir in session_dirs:
        for path in sorted(session_dir.rglob("*.jsonl"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            stat = path.stat()
            entry = SessionFileInventoryEntry(
                file_key=session_file_key(path),
                path=path,
                session_dir=session_dir,
                storage_state=storage_state_for_session_dir(session_dir),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
            existing = selected.get(entry.file_key)
            if existing is None or _inventory_priority(entry) < _inventory_priority(existing):
                selected[entry.file_key] = entry
    return sorted(selected.values(), key=lambda entry: str(entry.path).casefold())


def collect_jsonl_files(session_dirs: list[Path]) -> list[Path]:
    return [entry.path for entry in collect_session_file_inventory(session_dirs)]


def session_file_key(path: Path) -> str:
    metadata = read_session_metadata(path)
    if metadata and metadata.session_id:
        return metadata.session_id
    return path.stem


def storage_state_for_session_dir(session_dir: Path) -> str:
    name = session_dir.name.casefold()
    if name == ARCHIVED_SESSION_DIR_NAME:
        return "archived"
    if name == ACTIVE_SESSION_DIR_NAME:
        return "active"
    return "other"


def storage_snapshots() -> list[StorageRootSnapshot]:
    roots: list[StorageRootSnapshot] = []
    codex_homes = _candidate_codex_homes(codex_home=os.getenv("CODEX_HOME"), userprofile=os.getenv("USERPROFILE"))
    for codex_home in codex_homes:
        names = [ACTIVE_SESSION_DIR_NAME, ARCHIVED_SESSION_DIR_NAME]
        if codex_home.is_dir():
            names.extend(
                child.name
                for child in codex_home.iterdir()
                if child.is_dir() and child.name.endswith("_sessions") and child.name not in names
            )
        for name in dict.fromkeys(names):
            path = codex_home / name
            files = list(path.rglob("*.jsonl")) if path.is_dir() else []
            roots.append(
                StorageRootSnapshot(
                    path=path,
                    storage_state="active" if name == ACTIVE_SESSION_DIR_NAME else ("archived" if name == ARCHIVED_SESSION_DIR_NAME else name),
                    exists=path.is_dir(),
                    jsonl_count=len(files),
                    total_bytes=sum(file.stat().st_size for file in files if file.is_file()),
                )
            )
    return roots


def _candidate_codex_homes(
    *,
    codex_home: str | None = None,
    userprofile: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    if codex_home:
        return [Path(codex_home).expanduser()]
    candidates: list[Path] = []
    if userprofile:
        candidates.append(Path(userprofile).expanduser() / ".codex")
    candidates.append((home or Path.home()) / ".codex")
    return _dedupe_paths(candidates)


def _inventory_priority(entry: SessionFileInventoryEntry) -> tuple[int, int, str]:
    state_priority = 0 if entry.storage_state == "active" else 1 if entry.storage_state == "archived" else 2
    return (state_priority, -entry.mtime_ns, str(entry.path).casefold())


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = path.expanduser()
        key = str(expanded).rstrip("\\/").casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(expanded)
    return out
```

- [ ] **Step 4: Delegate `discovery.py` to `session_inventory.py`**

Replace `src/codex_usage/discovery.py` with:

```python
from __future__ import annotations

from pathlib import Path

from codex_usage.session_inventory import (
    candidate_session_dirs,
    collect_jsonl_files,
    default_session_dir,
    find_session_dirs,
)

__all__ = [
    "candidate_session_dirs",
    "collect_jsonl_files",
    "default_session_dir",
    "find_session_dirs",
]
```

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
uv run pytest tests/test_discovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/codex_usage/session_inventory.py src/codex_usage/discovery.py tests/test_discovery.py
git commit -m "feat: discover archived Codex sessions"
```

---

### Task 3: Add Storage Snapshot Command For Delete Experiment

**Files:**
- Modify: `src/codex_usage/cli.py`
- Modify: `src/codex_usage/session_inventory.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Append to `tests/test_cli.py`:

```python
def test_storage_snapshot_reports_active_and_archived_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    _write_session(sessions, "active-thread", "/repo/active", 10)
    _write_session(archived, "archived-thread", "/repo/archived", 20)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    exit_code = cli_main(["storage", "snapshot", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    roots = {Path(row["path"]).name: row for row in payload["roots"]}
    assert roots["sessions"]["jsonl_count"] == 1
    assert roots["archived_sessions"]["jsonl_count"] == 1
```

Use the existing `cli_main` and `_write_session` helpers in `tests/test_cli.py`.

- [ ] **Step 2: Run focused test and verify it fails**

Run:

```powershell
uv run pytest tests/test_cli.py::test_storage_snapshot_reports_active_and_archived_roots -q
```

Expected: FAIL because `storage snapshot` is not registered.

- [ ] **Step 3: Add CLI parser branch**

In `build_parser()` in `src/codex_usage/cli.py`, add:

```python
    storage_parser = subparsers.add_parser("storage", help="Inspect local Codex storage state.")
    storage_subparsers = storage_parser.add_subparsers(dest="storage_command")
    storage_parser.set_defaults(handler=handle_subparser_help, help_parser=storage_parser)

    storage_snapshot_parser = storage_subparsers.add_parser("snapshot", help="Print a local Codex storage snapshot.")
    storage_snapshot_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    storage_snapshot_parser.set_defaults(handler=handle_storage_snapshot)
```

- [ ] **Step 4: Add handler**

Import `storage_snapshots` from `codex_usage.session_inventory`.

Add this function to `src/codex_usage/cli.py`:

```python
def handle_storage_snapshot(args: argparse.Namespace) -> int:
    roots = [
        {
            "path": str(snapshot.path),
            "storage_state": snapshot.storage_state,
            "exists": snapshot.exists,
            "jsonl_count": snapshot.jsonl_count,
            "total_bytes": snapshot.total_bytes,
        }
        for snapshot in storage_snapshots()
    ]
    payload = {"roots": roots}
    if args.json:
        print_json(payload)
    else:
        for root in roots:
            exists = "yes" if root["exists"] else "no"
            print(f'{root["storage_state"]:>12} {exists:>3} {root["jsonl_count"]:>5} files {root["total_bytes"]:>12} bytes {root["path"]}')
    return 0
```

- [ ] **Step 5: Run focused test and verify it passes**

Run:

```powershell
uv run pytest tests/test_cli.py::test_storage_snapshot_reports_active_and_archived_roots -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/codex_usage/cli.py src/codex_usage/session_inventory.py tests/test_cli.py
git commit -m "feat: add Codex storage snapshot command"
```

---

### Task 4: Preserve Missing Files In Usage Cache

**Files:**
- Modify: `src/codex_usage/session_cache.py`
- Test: `tests/test_session_cache.py`

- [ ] **Step 1: Write failing cache tests**

Replace `test_removed_file_deletes_cached_rows` in `tests/test_session_cache.py` with:

```python
def test_removed_file_retains_cached_usage_as_missing(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first = _write_session(sessions, "thread-1", "/repo/one", 100)
    _write_session(sessions, "thread-2", "/repo/two", 75)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    first.unlink()

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_missing_retained == 1
    assert sorted(record.session_id for record in data.records) == ["thread-1", "thread-2"]
    assert sum(record.usage.total_tokens for record in data.records) == 175
```

Add:

```python
def test_archived_move_does_not_double_count_cached_usage(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active = _write_session(sessions, "thread-1", "/repo/one", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions, archived], cache_dir=cache_dir, auto_transitions=False)

    archived_path = archived / "2026" / "04" / "29" / active.name
    archived_path.parent.mkdir(parents=True)
    active.replace(archived_path)

    data = load_cached_session_data([sessions, archived], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_total == 1
    assert data.stats.files_missing_retained == 0
    assert [record.session_id for record in data.records] == ["thread-1"]
    assert [record.usage.total_tokens for record in data.records] == [100]
```

Add:

```python
def test_active_and_archived_duplicate_prefers_active_file(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active = _write_session(sessions, "thread-1", "/repo/active", 100)
    _write_session(archived, "thread-1", "/repo/archived", 100)
    cache_dir = tmp_path / "cache"

    data = load_cached_session_data([sessions, archived], cache_dir=cache_dir, auto_transitions=False)

    assert data.files == [active]
    assert [record.cwd for record in data.records] == ["/repo/active"]
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_session_cache.py -q
```

Expected: FAIL because the cache still deletes rows by missing path and lacks `files_missing_retained`.

- [ ] **Step 3: Update cache dataclasses and schema constants**

In `src/codex_usage/session_cache.py`:

```python
CACHE_SCHEMA_VERSION = 2
```

Extend `CacheStats`:

```python
    files_current: int = 0
    files_archived: int = 0
    files_missing_retained: int = 0
```

Extend `CachedFileSummary`:

```python
    file_key: str = ""
    storage_state: str = "active"
    is_missing: bool = False
```

Extend `CachedSessionData`:

```python
    retained_missing_files: list[Path] = field(default_factory=list)
```

Import `field` from `dataclasses` if needed.

- [ ] **Step 4: Change schema from path identity to file-key identity**

In `_ensure_schema()`, replace the `files`, `usage_records`, and `session_metadata` table definitions with:

```sql
        create table files (
            file_key text primary key,
            path text not null,
            session_dir text not null,
            storage_state text not null,
            size_bytes integer not null,
            mtime_ns integer not null,
            parsed_at text not null,
            last_seen_at text not null,
            missing_since text,
            is_missing integer not null,
            session_id text,
            error text
        );
        create table usage_records (
            file_key text not null,
            record_index integer not null,
            file_path text not null,
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
            primary key (file_key, record_index)
        );
        create table session_metadata (
            file_key text primary key,
            file_path text not null,
            session_dir text not null,
            storage_state text not null,
            is_missing integer not null,
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
```

- [ ] **Step 5: Use inventory entries in refresh**

Import:

```python
from codex_usage.session_inventory import SessionFileInventoryEntry, collect_session_file_inventory
```

In `load_cached_session_data()`, replace:

```python
session_files = collect_jsonl_files(session_dirs)
```

with:

```python
inventory = collect_session_file_inventory(session_dirs)
session_files = [entry.path for entry in inventory]
```

Pass `inventory` into `_refresh_files()`, `_load_records_by_file()`, and `_load_file_summaries()`.

- [ ] **Step 6: Mark missing instead of deleting**

Replace `_refresh_files()` with logic shaped like:

```python
def _refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
) -> CacheStats:
    now = datetime.now(UTC).isoformat()
    cached_rows = {str(row["file_key"]): row for row in connection.execute("select file_key, path, size_bytes, mtime_ns, is_missing from files")}
    current_keys = {entry.file_key for entry in inventory}
    for file_key, row in cached_rows.items():
        if file_key not in current_keys and int(row["is_missing"]) == 0:
            connection.execute(
                "update files set is_missing = 1, missing_since = ?, last_seen_at = ? where file_key = ?",
                (now, now, file_key),
            )
            connection.execute("update session_metadata set is_missing = 1 where file_key = ?", (file_key,))

    parsed = 0
    reused = 0
    errors = 0
    for entry in inventory:
        cached = cached_rows.get(entry.file_key)
        if (
            cached
            and str(cached["path"]) == str(entry.path)
            and int(cached["size_bytes"]) == entry.size_bytes
            and int(cached["mtime_ns"]) == entry.mtime_ns
            and int(cached["is_missing"]) == 0
        ):
            reused += 1
            connection.execute("update files set last_seen_at = ? where file_key = ?", (now, entry.file_key))
            continue
        _record_count, error = _refresh_one_file(connection, session_dirs, entry)
        parsed += 1
        if error:
            errors += 1
    connection.commit()
    missing_count = connection.execute("select count(*) from files where is_missing = 1").fetchone()[0]
    return CacheStats(
        files_total=len(inventory),
        files_current=len(inventory),
        files_archived=sum(1 for entry in inventory if entry.storage_state == "archived"),
        files_parsed=parsed,
        files_reused=reused,
        files_removed=0,
        files_missing_retained=int(missing_count),
        file_errors=errors,
        rebuilt=rebuilt,
    )
```

- [ ] **Step 7: Refresh one file by `file_key`**

Change `_refresh_one_file()` signature:

```python
def _refresh_one_file(connection: sqlite3.Connection, session_dirs: list[Path], entry: SessionFileInventoryEntry) -> tuple[int, str]:
```

Inside it:

```python
path = entry.path
_delete_file_rows(connection, entry.file_key)
```

Insert records with `entry.file_key`. Insert file row with `file_key`, `path`, `storage_state`, `last_seen_at`, `missing_since = ""`, `is_missing = 0`.

- [ ] **Step 8: Update row deletion and inserts**

Change `_delete_file_rows()` to accept `file_key: str`:

```python
def _delete_file_rows(connection: sqlite3.Connection, file_key: str) -> None:
    connection.execute("delete from usage_records where file_key = ?", (file_key,))
    connection.execute("delete from session_metadata where file_key = ?", (file_key,))
```

Do not delete from `files` there; `_refresh_one_file()` should replace the `files` row after parsing.

Change `_insert_record()` to accept `file_key` and write both `file_key` and `file_path`.

Change `_insert_file_summary()` to accept the inventory entry and write `file_key`, `file_path`, `storage_state`, `is_missing = 0`.

- [ ] **Step 9: Load current plus missing records for summaries**

Change `_load_records_by_file()` into `_load_records_by_file_key()`:

```python
def _load_records_by_file_key(connection: sqlite3.Connection, selected_keys: set[str], include_missing: bool) -> dict[str, list[UsageRecord]]:
```

For usage summaries, call it with all current keys plus cached missing keys:

```python
missing_keys = _missing_file_keys(connection)
records_by_key = _load_records_by_file_key(connection, {entry.file_key for entry in inventory} | missing_keys, include_missing=True)
records = finalize_session_records([records_by_key.get(key, []) for key in sorted(records_by_key)])
```

When converting a row to `UsageRecord`, use `file_path` from the row so retained missing records still show their last known path.

- [ ] **Step 10: Keep sync summaries current-only**

Update `_load_file_summaries()` so it returns summaries for current inventory only by default:

```python
selected_keys = {entry.file_key for entry in inventory}
...
if row["file_key"] not in selected_keys:
    continue
```

This keeps `threads` and sync export focused on existing files.

- [ ] **Step 11: Run focused tests and verify they pass**

Run:

```powershell
uv run pytest tests/test_session_cache.py -q
```

Expected: PASS.

- [ ] **Step 12: Commit**

```powershell
git add src/codex_usage/session_cache.py tests/test_session_cache.py
git commit -m "feat: retain usage for missing Codex sessions"
```

---

### Task 5: Add Summary And Report Metadata

**Files:**
- Modify: `src/codex_usage/cli.py`
- Modify: `src/codex_usage/reporting.py`
- Modify: summary payload module used by `summary_payload()`
- Test: `tests/test_cli.py`
- Test: `tests/test_reporting_html.py`

- [ ] **Step 1: Write failing JSON metadata test**

Add to `tests/test_cli.py`:

```python
def test_summary_json_reports_archived_and_retained_missing_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active_path = _write_session(sessions, "active-thread", "/repo/active", 10)
    _write_session(archived, "archived-thread", "/repo/archived", 20)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert cli_main(["summary", "--range", "all", "--by", "project", "--json"]) == 0
    active_path.unlink()

    assert cli_main(["summary", "--range", "all", "--by", "project", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["files_archived"] == 1
    assert payload["files_retained_missing"] == 1
```

- [ ] **Step 2: Write failing HTML metadata test**

Add to `tests/test_reporting_html.py`:

```python
def test_report_html_mentions_archived_and_retained_missing_files() -> None:
    html = render_report_html(
        view=sample_report_view(files_archived=2, files_retained_missing=1),
        theme="auto",
    )

    assert "Archived files included: 2" in html
    assert "Retained missing files: 1" in html
```

If the existing report tests do not have `sample_report_view`, add the equivalent fields to the existing report view fixture.

- [ ] **Step 3: Run focused tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_cli.py::test_summary_json_reports_archived_and_retained_missing_counts tests/test_reporting_html.py::test_report_html_mentions_archived_and_retained_missing_files -q
```

Expected: FAIL because metadata is not exposed yet.

- [ ] **Step 4: Add metadata to context and JSON payload**

Extend `_Context` in `src/codex_usage/cli.py`:

```python
        storage_stats: CacheStats,
```

Set it from `data.stats` in `_load_context()`.

Pass to `summary_payload()`:

```python
files_archived=context.storage_stats.files_archived,
files_retained_missing=context.storage_stats.files_missing_retained,
storage_roots=[str(path) for path in context.session_dirs],
```

Add these fields to the payload builder:

```python
"storage_roots": storage_roots,
"files_archived": files_archived,
"files_retained_missing": files_retained_missing,
```

- [ ] **Step 5: Add report view fields**

Add fields to the report view model:

```python
files_archived: int = 0
files_retained_missing: int = 0
storage_roots: tuple[str, ...] = ()
```

When building the report view, pass values from `context.storage_stats`.

- [ ] **Step 6: Render report header metadata**

In `src/codex_usage/reporting.py`, add a header line near files scanned:

```python
storage_bits = [f"Files scanned: {view.files_scanned}"]
if view.files_archived:
    storage_bits.append(f"Archived files included: {view.files_archived}")
if view.files_retained_missing:
    storage_bits.append(f"Retained missing files: {view.files_retained_missing}")
```

Render joined text:

```html
<p class="muted">Files scanned: 208 | Archived files included: 6 | Retained missing files: 1</p>
```

- [ ] **Step 7: Run focused tests and verify they pass**

Run:

```powershell
uv run pytest tests/test_cli.py::test_summary_json_reports_archived_and_retained_missing_counts tests/test_reporting_html.py::test_report_html_mentions_archived_and_retained_missing_files -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add src/codex_usage/cli.py src/codex_usage/reporting.py src/codex_usage/summary.py tests/test_cli.py tests/test_reporting_html.py
git commit -m "feat: report archived and retained usage metadata"
```

---

### Task 6: Keep Sync Conversation Listing Current-Only

**Files:**
- Modify: `src/codex_usage/threads.py`
- Test: `tests/test_sync.py` or create `tests/test_threads.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_threads.py`:

```python
from pathlib import Path

from codex_usage.session_cache import load_cached_session_data
from codex_usage.threads import list_threads_from_cached_data

from tests.test_session_cache import _write_session


def test_thread_listing_excludes_retained_missing_files(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/one", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    session_path.unlink()
    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    threads = list_threads_from_cached_data(data)

    assert threads == []
```

- [ ] **Step 2: Run focused test and verify it fails if current implementation includes retained missing summaries**

Run:

```powershell
uv run pytest tests/test_threads.py::test_thread_listing_excludes_retained_missing_files -q
```

Expected: PASS if Task 4 already kept `file_summaries` current-only; FAIL if retained missing summaries leak into thread listing.

- [ ] **Step 3: Implement only if test fails**

If the test fails, update `list_threads_from_cached_data()` to ignore summaries where `summary.is_missing` is true:

```python
for summary in data.file_summaries.values():
    if getattr(summary, "is_missing", False):
        continue
```

- [ ] **Step 4: Run focused test**

Run:

```powershell
uv run pytest tests/test_threads.py::test_thread_listing_excludes_retained_missing_files -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/codex_usage/threads.py tests/test_threads.py
git commit -m "test: keep sync conversations current only"
```

---

### Task 7: Document The Delete Experiment Protocol

**Files:**
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `PRIVACY.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update README**

Add a section:

```markdown
## Archived And Deleted Conversations

The dashboard treats token usage as historical usage. Archiving a Codex conversation moves its JSONL file to `archived_sessions`, and those files are included in totals. If a conversation file disappears after the dashboard cache has seen it, its parsed usage is retained as historical usage and marked as a retained missing file.

To observe how your installed Codex build handles deletion:

```powershell
codex-usage storage snapshot --json > output\before-delete.json
# delete one test conversation in Codex
codex-usage storage snapshot --json > output\after-delete.json
codex-usage summary --range all --by project --json > output\after-delete-summary.json
```

Do not use a conversation you still need for sync testing. The dashboard can preserve usage after it has parsed a file, but it cannot restore a deleted Codex conversation.
```

- [ ] **Step 2: Update extension README**

Add:

```markdown
### Archive/Delete Accounting

Archived Codex conversations are included in usage totals. Deleted or otherwise missing conversations are retained in historical totals after the local cache has parsed them once. The dashboard header shows archived and retained missing file counts when applicable.
```

- [ ] **Step 3: Update privacy docs**

Add:

```markdown
The local cache may retain parsed token usage for session files that were later archived or deleted locally. This retained data stays on your machine under the extension/global Codex Usage cache and is used only for historical accounting.
```

- [ ] **Step 4: Add changelog entry**

Add at top:

```markdown
## 0.1.19 - Archive/Delete Resilient Usage

- Included Codex `archived_sessions` in usage totals.
- Preserved cached historical usage when previously parsed session files disappear locally.
- Added `codex-usage storage snapshot --json` to support before/after delete behavior experiments.
- Avoided double-counting session files moved between active and archived storage.
```

- [ ] **Step 5: Commit**

```powershell
git add README.md extensions/vscode/README.md PRIVACY.md CHANGELOG.md
git commit -m "docs: explain archive and delete accounting"
```

---

### Task 8: Bump Versions And Verify

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

- [ ] **Step 1: Bump versions to `0.1.19`**

Set Python and VS Code package versions:

```toml
version = "0.1.19"
```

```json
"version": "0.1.19"
```

Update `uv.lock` and `extensions/vscode/package-lock.json` package versions to `0.1.19`.

- [ ] **Step 2: Run full Python tests**

Run:

```powershell
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 3: Run full TypeScript tests**

Run:

```powershell
Push-Location extensions/vscode
npm test
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 4: Run real local storage snapshot**

Run:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-before-delete-experiment.json
```

Expected: JSON includes at least `sessions` and `archived_sessions` root entries.

- [ ] **Step 5: Run real local archive-inclusive summary**

Run:

```powershell
uv run codex-usage summary --range all --by project --json > output\archive-inclusive-summary.json
```

Expected: JSON includes `files_archived` greater than zero on this machine while archived sessions exist.

- [ ] **Step 6: Build Windows VSIX**

Run:

```powershell
Push-Location extensions/vscode
npm run package:vsix:win
Pop-Location
```

Expected:

```text
Packaged: ../../output/codex-usage-dashboard-win32-x64.vsix
```

- [ ] **Step 7: Smoke bundled executable**

Run:

```powershell
extensions\vscode\bin\win32-x64\codex-usage.exe storage snapshot --json > output\bundled-storage-snapshot.json
extensions\vscode\bin\win32-x64\codex-usage.exe report --range all --output output\archive-delete-report-smoke.html
```

Expected:

```text
Wrote output\archive-delete-report-smoke.html
```

- [ ] **Step 8: Commit**

```powershell
git add pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json
git commit -m "chore: bump archive delete accounting beta"
```

---

### Task 9: Manual Delete Experiment

**Files:**
- Generated: `output/storage-snapshot-before-delete-experiment.json`
- Generated: `output/storage-snapshot-after-delete-experiment.json`
- Generated: `output/delete-experiment-summary.json`

- [ ] **Step 1: Capture before snapshot**

Run:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-before-delete-experiment.json
uv run codex-usage summary --range all --by session --json > output\delete-experiment-before-summary.json
```

Expected: both files are written.

- [ ] **Step 2: User deletes one nonessential Codex conversation in the Codex app**

Choose a conversation that does not matter for sync/resume testing. Do not delete a conversation needed for current work.

- [ ] **Step 3: Capture after snapshot and summary**

Run:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-after-delete-experiment.json
uv run codex-usage summary --range all --by session --json > output\delete-experiment-after-summary.json
```

Expected:
- If Codex removes the JSONL file, the after snapshot has one fewer file in its original storage root and the summary reports one more retained missing file.
- If Codex moves the JSONL file into a new storage folder such as `deleted_sessions`, the after snapshot shows that folder. Usage totals remain stable because the cache already retained the file by stable key.
- If Codex only hides the conversation in app metadata and leaves the JSONL in place, file counts and retained missing counts remain unchanged.

- [ ] **Step 4: Record observed behavior in docs**

Add a short note to `docs/release.md` using the measured result from the before/after snapshots. Use exactly one of these three forms:

```markdown
## Codex Delete Behavior Observation

Observed on Windows with Codex app build current as of 2026-05-27:

- Archive moves session JSONL files from `sessions` to `archived_sessions`.
- Delete removed the session JSONL from local Codex storage; Codex Usage retained historical usage from cache.
```

or:

```markdown
## Codex Delete Behavior Observation

Observed on Windows with Codex app build current as of 2026-05-27:

- Archive moves session JSONL files from `sessions` to `archived_sessions`.
- Delete moved the session JSONL into a separate local storage folder named `deleted_sessions`; Codex Usage retained historical usage from cache.
```

or:

```markdown
## Codex Delete Behavior Observation

Observed on Windows with Codex app build current as of 2026-05-27:

- Archive moves session JSONL files from `sessions` to `archived_sessions`.
- Delete changed app-visible conversation state without moving or removing the session JSONL file.
```

- [ ] **Step 5: Commit observation**

```powershell
git add docs/release.md
git commit -m "docs: record Codex delete storage behavior"
```

---

## Self-Review

- Spec coverage: The plan includes archive inclusion, no-assumption delete observation, durable missing-file historical accounting, move dedupe, sync-current-only behavior, metadata/report transparency, docs, tests, packaging, and a real manual experiment protocol.
- Red-flag scan: No deferred-work markers or vague implementation steps remain. The manual observation step provides three concrete text forms so the measured result can be recorded without inventing wording during execution.
- Type consistency: `file_key`, `storage_state`, `files_archived`, and `files_missing_retained` are used consistently across inventory, cache, CLI metadata, and report rendering.
