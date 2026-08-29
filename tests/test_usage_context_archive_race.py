from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_usage.usage_context as usage_context
from codex_usage.direct_parse_recovery import (
    build_direct_parse_targets,
    parse_direct_files,
)
from codex_usage.parser import parse_session_file
from codex_usage.models import ROOT_USAGE_ROLE, TokenUsage, UsageRecord
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
)


def test_direct_parse_recovers_rename_after_inventory_without_restarting(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    archived = tmp_path / "codex" / "archived_sessions"
    first = _write_session(sessions, "first")
    moving = _write_session(sessions, "moving")
    relocated = archived / moving.relative_to(sessions)
    inventory = collect_session_file_inventory(
        [sessions, archived], read_metadata=True
    )
    targets = build_direct_parse_targets(
        [first, moving], inventory, [sessions, archived]
    )
    calls: list[Path] = []
    moved = False

    def parse_one(path: Path):
        nonlocal moved
        calls.append(path)
        if path == moving and not moved:
            relocated.parent.mkdir(parents=True, exist_ok=True)
            moving.rename(relocated)
            moved = True
        return parse_session_file(path)

    result = parse_direct_files(
        targets,
        session_dirs=[sessions, archived],
        parse_file=parse_one,
    )

    assert calls == [first, moving, relocated]
    assert calls.count(first) == 1
    assert calls.count(relocated) == 1
    assert result.files == [first, relocated]
    assert [record.session_id for record in result.records] == ["first", "moving"]
    assert all(record.file_path != moving for record in result.records)


def test_direct_parse_keeps_genuine_disappearance_explicit(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_session(sessions, "gone")
    inventory = collect_session_file_inventory([sessions], read_metadata=True)
    targets = build_direct_parse_targets([path], inventory, [sessions])

    def disappear_then_parse(candidate: Path):
        candidate.unlink()
        return parse_session_file(candidate)

    with pytest.raises(
        FileNotFoundError,
        match="identity-aware relocation discovery found no replacement",
    ):
        parse_direct_files(
            targets,
            session_dirs=[sessions],
            parse_file=disappear_then_parse,
        )


def test_usage_context_fallback_reparses_only_relocated_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    archived = tmp_path / "codex" / "archived_sessions"
    moving = _write_session(sessions, "moving")
    relocated = archived / moving.relative_to(sessions)
    original_parse = usage_context.parse_session_files
    calls: list[Path] = []
    moved = False

    def parse_with_race(paths: list[Path]):
        nonlocal moved
        path = paths[0]
        calls.append(path)
        if path == moving and not moved:
            relocated.parent.mkdir(parents=True, exist_ok=True)
            moving.rename(relocated)
            moved = True
        return original_parse(paths)

    monkeypatch.setattr(
        usage_context,
        "load_cached_session_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("cache unavailable")
        ),
    )
    monkeypatch.setattr(usage_context, "parse_session_files", parse_with_race)

    data = usage_context.load_session_data(
        [sessions, archived],
        auto_transitions=False,
    )

    assert calls == [moving, relocated]
    assert data.files == [relocated]
    assert [record.session_id for record in data.records] == ["moving"]


def test_usage_context_filters_direct_fallback_with_same_range_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = Path("/sessions")
    now = datetime.now(UTC)
    today = _usage_record(now, "/repo/today")
    yesterday = _usage_record(now - timedelta(days=1), "/repo/yesterday")

    monkeypatch.setattr(usage_context, "find_session_dirs", lambda: [sessions])
    monkeypatch.setattr(
        usage_context,
        "load_cached_session_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("cache unavailable")
        ),
    )

    def inventory(_dirs, *, read_metadata=True):
        if not read_metadata:
            return []
        return [
            SessionFileInventoryEntry(
                file_key=record.session_id,
                path=record.file_path,
                session_dir=sessions,
                storage_state="active",
                size_bytes=0,
                mtime_ns=0,
            )
            for record in (today, yesterday)
        ]

    monkeypatch.setattr(usage_context, "collect_session_file_inventory", inventory)
    monkeypatch.setattr(
        usage_context,
        "parse_session_files",
        lambda _files: [today, yesterday],
    )

    context = usage_context.load_usage_context(
        SimpleNamespace(
            timezone="UTC",
            range_name="today",
            project_key=[],
            no_auto_transitions=True,
            parallel_audit=None,
        )
    )

    assert context.records == [today]


def _write_session(session_dir: Path, task_id: str) -> Path:
    path = session_dir / "2026" / "08" / "29" / f"{task_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-08-29T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": task_id, "cwd": "/repo/demo", "source": "cli"},
        },
        {
            "timestamp": "2026-08-29T12:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-terra"},
        },
        {
            "timestamp": "2026-08-29T12:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 80,
                        "output_tokens": 20,
                        "total_tokens": 100,
                    }
                },
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _usage_record(timestamp: datetime, project_key: str) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp,
        usage=TokenUsage(total_tokens=1),
        session_id=f"session-{project_key.rsplit('/', maxsplit=1)[-1]}",
        file_path=Path(f"{project_key}/session.jsonl"),
        usage_role=ROOT_USAGE_ROLE,
        project_key=project_key,
        project_label=project_key.rsplit("/", maxsplit=1)[-1],
    )
