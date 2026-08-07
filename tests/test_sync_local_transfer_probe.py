from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import Any, Self

import pytest

import codex_usage.parser as parser_module
import codex_usage.sync.io as sync_io
from codex_usage.sync import load_local_transfer_probe

_TRANSFER_METADATA_HEADER_READ_LIMIT = 1024 * 1024


class _ReadBudgetFile:
    def __init__(self, handle: Any, limit: int, observed: list[int]) -> None:
        self._handle = handle
        self._limit = limit
        self._observed = observed

    def __enter__(self) -> Self:
        self._handle.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._handle.__exit__(*args)

    def __iter__(self) -> _ReadBudgetFile:
        return self

    def __next__(self) -> Any:
        line = self.readline()
        if line == b"" or line == "":
            raise StopIteration
        return line

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def read(self, size: int = -1) -> Any:
        return self._record(self._handle.read(size))

    def readline(self, size: int = -1) -> Any:
        return self._record(self._handle.readline(size))

    def _record(self, value: Any) -> Any:
        self._observed[0] += len(value)
        if self._observed[0] > self._limit:
            raise AssertionError(
                "Task Transfer metadata read exceeded its header budget"
            )
        return value


def _write_meta(
    path: Path,
    thread_id: str,
    *,
    cwd: str = "/repo/demo",
    source: object = "cli",
    timestamp: str = "2026-07-31T12:00:00Z",
    repo: str = "",
    trailing_bytes: int = 0,
) -> None:
    payload: dict[str, object] = {
        "id": thread_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "source": source,
    }
    if repo:
        payload["git"] = {"repository_url": repo}
    event = {"timestamp": timestamp, "type": "session_meta", "payload": payload}
    path.write_text(
        json.dumps(event) + "\n" + ("x" * trailing_bytes),
        encoding="utf-8",
    )


def test_local_probe_lists_only_active_root_tasks(tmp_path: Path) -> None:
    active = tmp_path / ".codex" / "sessions"
    archived = tmp_path / ".codex" / "archived_sessions"
    active.mkdir(parents=True)
    archived.mkdir(parents=True)
    _write_meta(active / "root.jsonl", "root", source="cli")
    _write_meta(
        active / "spawned.jsonl",
        "spawned",
        source={"subagent": {"thread_spawn": {"parent_thread_id": "root"}}},
    )
    _write_meta(
        active / "guardian.jsonl",
        "guardian",
        source={"subagent": {"other": "guardian"}},
    )
    _write_meta(archived / "archived.jsonl", "archived", source="cli")

    probe = load_local_transfer_probe([active, archived])

    assert list(probe.inventory.threads) == ["root"]
    assert probe.inventory.discovered_count == 1
    assert probe.issues == ()


def test_local_probe_does_not_require_session_index(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / "root.jsonl", "root", cwd="/repo/demo", source="cli")
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert thread.title == "demo"
    assert thread.total_tokens == 0


def test_local_probe_never_calls_usage_parser_or_hasher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "root.jsonl",
        "root",
        source="cli",
        trailing_bytes=2_000_000,
    )
    monkeypatch.setattr(
        parser_module,
        "parse_session_file",
        lambda path: pytest.fail("usage parser called"),
    )
    monkeypatch.setattr(
        sync_io,
        "snapshot_file",
        lambda path: pytest.fail("full hash called"),
    )
    assert list(load_local_transfer_probe([sessions]).inventory.threads) == ["root"]


def test_local_probe_stops_reading_after_first_valid_session_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "root.jsonl"
    _write_meta(path, "root", trailing_bytes=4_000_000)
    first_line_bytes = len(path.read_bytes().splitlines(keepends=True)[0])
    original_open = Path.open
    observed = [0]
    observed_buffering: list[int] = []

    def budgeted_open(candidate: Path, *args: object, **kwargs: object) -> Any:
        handle = original_open(candidate, *args, **kwargs)
        if candidate == path:
            observed_buffering.append(int(kwargs.get("buffering", -1)))
            return _ReadBudgetFile(
                handle,
                _TRANSFER_METADATA_HEADER_READ_LIMIT,
                observed,
            )
        return handle

    monkeypatch.setattr(Path, "open", budgeted_open)

    probe = load_local_transfer_probe([sessions])

    assert list(probe.inventory.threads) == ["root"]
    assert observed[0] == first_line_bytes
    assert observed_buffering and observed_buffering[0] > 0


def test_local_probe_finds_metadata_after_irrelevant_rows(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "root.jsonl"
    metadata = {
        "timestamp": "2026-07-31T12:00:00Z",
        "type": "session_meta",
        "payload": {"id": "root", "cwd": "/repo/demo", "source": "cli"},
    }
    path.write_text(
        json.dumps({"type": "event_msg", "payload": {}})
        + "\nnot-json\n"
        + json.dumps(metadata)
        + "\n"
        + ("x" * 2_000_000),
        encoding="utf-8",
    )

    probe = load_local_transfer_probe([sessions])

    assert list(probe.inventory.threads) == ["root"]


@pytest.mark.parametrize(
    "payload",
    [
        {"cwd": "/repo/demo", "source": "cli"},
        {"id": " padded ", "cwd": "/repo/demo", "source": "cli"},
        ["not", "an", "object"],
    ],
    ids=["missing-id", "noncanonical-id", "non-object-payload"],
)
def test_local_probe_requires_object_payload_with_explicit_canonical_id(
    tmp_path: Path,
    payload: object,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "fallback-id.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:00Z",
                "type": "session_meta",
                "payload": payload,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    probe = load_local_transfer_probe([sessions])

    assert probe.inventory.threads == {}
    assert [issue.code for issue in probe.issues] == [
        "local_session_metadata_unreadable"
    ]


def test_local_probe_bounds_large_metadata_free_file_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "large-metadata-free.jsonl"
    path.write_bytes(
        b'{"type":"event_msg","payload":{}}\n'
        + b"x" * (_TRANSFER_METADATA_HEADER_READ_LIMIT * 4)
    )
    original_open = Path.open
    observed = [0]

    def budgeted_open(candidate: Path, *args: object, **kwargs: object) -> Any:
        handle = original_open(candidate, *args, **kwargs)
        if candidate == path:
            return _ReadBudgetFile(
                handle,
                _TRANSFER_METADATA_HEADER_READ_LIMIT,
                observed,
            )
        return handle

    monkeypatch.setattr(Path, "open", budgeted_open)

    probe = load_local_transfer_probe([sessions])

    assert probe.inventory.threads == {}
    assert [issue.code for issue in probe.issues] == [
        "local_session_metadata_unreadable"
    ]
    assert observed[0] <= _TRANSFER_METADATA_HEADER_READ_LIMIT


def test_local_probe_retries_transient_metadata_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "root.jsonl"
    _write_meta(path, "root")
    original_open = Path.open
    attempts = 0

    def flaky_open(candidate: Path, *args: object, **kwargs: object) -> Any:
        nonlocal attempts
        if candidate == path:
            attempts += 1
            if attempts < 3:
                raise OSError(errno.EBUSY, "local metadata is busy")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    probe = load_local_transfer_probe([sessions])

    assert attempts == 3
    assert list(probe.inventory.threads) == ["root"]
    assert probe.issues == ()


def _sessions_with_root(tmp_path: Path, thread_id: str, *, cwd: str) -> Path:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / f"{thread_id}.jsonl", thread_id, cwd=cwd, source="cli")
    return sessions


def _write_index(path: Path, thread_id: str, title: str, updated_at: str) -> None:
    path.write_text(
        json.dumps({"id": thread_id, "thread_name": title, "updated_at": updated_at}) + "\n",
        encoding="utf-8",
    )


def test_local_probe_prefers_index_display_metadata(tmp_path: Path) -> None:
    sessions = _sessions_with_root(tmp_path, "root", cwd="/repo/demo")
    _write_index(
        tmp_path / ".codex" / "session_index.jsonl",
        "root",
        "Indexed title",
        "2026-07-31T13:00:00Z",
    )
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert (thread.title, thread.updated_at) == (
        "Indexed title",
        "2026-07-31T13:00:00Z",
    )


def test_local_probe_reports_malformed_metadata(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "broken.jsonl").write_text("not-json\n", encoding="utf-8")
    probe = load_local_transfer_probe([sessions])
    assert probe.inventory.threads == {}
    assert [issue.code for issue in probe.issues] == [
        "local_session_metadata_unreadable"
    ]


def test_local_probe_keeps_newest_duplicate_active_identity(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "old.jsonl",
        "root",
        timestamp="2026-07-30T12:00:00Z",
        source="cli",
    )
    _write_meta(
        sessions / "new.jsonl",
        "root",
        timestamp="2026-07-31T12:00:00Z",
        source="cli",
    )
    assert (
        load_local_transfer_probe([sessions])
        .inventory.threads["root"]
        .session_path.name
        == "new.jsonl"
    )


def test_local_probe_uses_portable_git_identity_for_windows_cwd(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "root.jsonl",
        "root",
        cwd=r"D:\Projects\Demo",
        repo="https://github.com/Example/Demo.git",
    )
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert thread.project_key == "https://github.com/example/demo"
    assert thread.project_label == "demo"
    assert "d:/projects/demo" in thread.project_aliases
