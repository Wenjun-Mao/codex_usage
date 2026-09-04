from __future__ import annotations

import json
import subprocess
from pathlib import Path

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import load_ledger_records
from codex_usage.models import SessionMetadata
from codex_usage.parser import parse_session_files
from codex_usage.project_identity import resolve_project_identity


_RECORDED_ORIGIN = "https://github.com/example/original-widget.git"
_REPLACEMENT_ORIGIN = "https://github.com/fork/widget.git"


def test_verified_checkout_replacement_rebinds_root_and_descendants(
    tmp_path: Path,
) -> None:
    checkout, commit_hash = _checkout_with_replacement_origin(tmp_path / "widget")
    root = _write_session(
        tmp_path / "sessions" / "root.jsonl",
        session_id="root-task",
        cwd=checkout,
        repository_url=_RECORDED_ORIGIN,
        commit_hash=commit_hash,
        total=100,
    )
    child = _write_session(
        tmp_path / "sessions" / "child.jsonl",
        session_id="child-task",
        cwd=checkout,
        repository_url=_RECORDED_ORIGIN,
        parent_thread_id="root-task",
        total=50,
    )

    records = parse_session_files([root, child])

    assert {record.project_key for record in records} == {
        "https://github.com/fork/widget"
    }
    root_record = next(record for record in records if record.session_id == "root-task")
    assert "https://github.com/example/original-widget" in root_record.project_aliases
    child_record = next(record for record in records if record.session_id == "child-task")
    assert child_record.git_repository_url == "https://github.com/fork/widget"


def test_unverified_same_named_repository_remains_separate(tmp_path: Path) -> None:
    checkout, _commit_hash = _checkout_with_replacement_origin(tmp_path / "widget")

    identity = resolve_project_identity(
        SessionMetadata(
            session_id="unrelated-task",
            file_path=tmp_path / "session.jsonl",
            cwd=str(checkout),
            git_repository_url=_RECORDED_ORIGIN,
            git_commit_hash="f" * 40,
        )
    )

    assert identity.key == "https://github.com/example/original-widget"
    assert identity.uses_current_checkout_origin is False


def test_verified_replacement_uses_the_linked_worktree_common_origin(
    tmp_path: Path,
) -> None:
    checkout, commit_hash = _checkout_with_replacement_origin(tmp_path / "primary")
    linked_checkout = tmp_path / "linked"
    _git(checkout, "worktree", "add", "-b", "linked", str(linked_checkout))

    identity = resolve_project_identity(
        SessionMetadata(
            session_id="linked-task",
            file_path=tmp_path / "session.jsonl",
            cwd=str(linked_checkout),
            git_repository_url=_RECORDED_ORIGIN,
            git_commit_hash=commit_hash,
        )
    )

    assert identity.key == "https://github.com/fork/widget"
    assert identity.uses_current_checkout_origin is True


def test_capture_rebuilds_normalized_ledger_ownership_from_root_lineage(
    tmp_path: Path,
) -> None:
    checkout, commit_hash = _checkout_with_replacement_origin(tmp_path / "widget")
    home = tmp_path / ".codex"
    _write_session(
        home / "sessions" / "2026" / "09" / "03" / "root.jsonl",
        session_id="root-task",
        cwd=checkout,
        repository_url=_RECORDED_ORIGIN,
        commit_hash=commit_hash,
        total=100,
    )
    _write_session(
        home / "sessions" / "2026" / "09" / "03" / "child.jsonl",
        session_id="child-task",
        cwd=checkout,
        repository_url=_RECORDED_ORIGIN,
        parent_thread_id="root-task",
        total=50,
    )

    result = capture_once(home, request_kind="manual", max_workers=1)

    assert result.outcome == "success"
    records = load_ledger_records(ledger_database_path(home))
    assert {record.project_key for record in records} == {
        "https://github.com/fork/widget"
    }
    assert sum(record.usage.total_tokens for record in records) == 150


def test_cached_capture_rebinds_after_the_checkout_origin_changes(
    tmp_path: Path,
) -> None:
    checkout, commit_hash = _checkout_with_origin(
        tmp_path / "widget",
        _RECORDED_ORIGIN,
    )
    home = tmp_path / ".codex"
    _write_session(
        home / "sessions" / "2026" / "09" / "03" / "root.jsonl",
        session_id="root-task",
        cwd=checkout,
        repository_url=_RECORDED_ORIGIN,
        commit_hash=commit_hash,
        total=100,
    )
    _write_session(
        home / "sessions" / "2026" / "09" / "03" / "child.jsonl",
        session_id="child-task",
        cwd=checkout,
        repository_url=_RECORDED_ORIGIN,
        parent_thread_id="root-task",
        total=50,
    )

    assert capture_once(home, request_kind="startup", max_workers=1).outcome == "success"
    _git(checkout, "remote", "set-url", "origin", _REPLACEMENT_ORIGIN)

    result = capture_once(home, request_kind="scheduled", max_workers=1)

    assert result.outcome == "success"
    assert result.stats.files_parsed == 0
    assert {record.project_key for record in load_ledger_records(ledger_database_path(home))} == {
        "https://github.com/fork/widget"
    }


def _checkout_with_replacement_origin(path: Path) -> tuple[Path, str]:
    return _checkout_with_origin(path, _REPLACEMENT_ORIGIN)


def _checkout_with_origin(path: Path, origin: str) -> tuple[Path, str]:
    path.mkdir()
    _git(path.parent, "init", path.name)
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "README.md").write_text("widget\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial widget")
    _git(path, "remote", "add", "origin", origin)
    return path, _git(path, "rev-parse", "HEAD")


def _git(path: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_session(
    path: Path,
    *,
    session_id: str,
    cwd: Path,
    repository_url: str,
    total: int,
    commit_hash: str = "",
    parent_thread_id: str = "",
) -> Path:
    git: dict[str, str] = {"repository_url": repository_url, "branch": "main"}
    if commit_hash:
        git["commit_hash"] = commit_hash
    payload: dict[str, object] = {
        "id": session_id,
        "timestamp": "2026-09-03T10:00:00Z",
        "cwd": str(cwd),
        "git": git,
    }
    if parent_thread_id:
        payload["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_thread_id}}
        }
    rows = [
        {"timestamp": "2026-09-03T10:00:00Z", "type": "session_meta", "payload": payload},
        {"timestamp": "2026-09-03T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
        {
            "timestamp": "2026-09-03T10:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": total, "total_tokens": total}},
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path
