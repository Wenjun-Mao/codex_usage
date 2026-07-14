import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_usage.cli as cli_module
import codex_usage.sync_cli as sync_cli
from codex_usage.sync_cli import normalize_thread_ids


def test_cli_sync_run_replaces_import_and_export(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    source_day = source_home / "sessions" / "2026" / "04" / "29"
    source_day.mkdir(parents=True)
    _write_session(source_day / "thread-1.jsonl", "thread-1", "/repo/first", 100)
    (source_home / "session_index.jsonl").write_text(
        json.dumps(
            {
                "id": "thread-1",
                "thread_name": "First thread",
                "updated_at": "2026-04-29T10:05:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sync_dir = tmp_path / "sync"

    pushed = _run_cli(
        [
            "sync",
            "run",
            "--sync-dir",
            str(sync_dir),
            "--project-key",
            "/repo/first",
            "--json",
        ],
        env={"CODEX_HOME": str(source_home)},
    )

    assert json.loads(pushed.stdout)["outcome"] == "completed"
    assert json.loads(pushed.stdout)["counts"]["pushed"] == 1
    assert '"phase":"scanning"' in pushed.stderr.replace(" ", "")
    assert '"phase":"pulling"' not in pushed.stderr.replace(" ", "")

    target_home = tmp_path / "target"
    pulled = _run_cli(
        [
            "sync",
            "run",
            "--sync-dir",
            str(sync_dir),
            "--project-key",
            "/repo/first",
            "--json",
        ],
        env={"CODEX_HOME": str(target_home)},
    )

    assert json.loads(pulled.stdout)["counts"]["pulled"] == 1
    assert len(list((target_home / "sessions").rglob("*.jsonl"))) == 1


def test_cli_sync_help_exposes_only_run_and_status() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", "sync", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "{run,status}" in result.stdout
    assert "import" not in result.stdout
    assert "export" not in result.stdout
    assert "--conflict-policy" not in result.stdout


def test_sync_run_loads_cache_once_after_scanning_and_passes_normalized_selectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = object()
    calls: list[tuple[object, ...]] = []

    def load_session_data(paths: list[Path], *, auto_transitions: bool) -> object:
        calls.append(("load", paths, auto_transitions))
        return data

    def run_sync(**kwargs) -> SimpleNamespace:
        calls.append(("run", kwargs))
        return SimpleNamespace(
            outcome="completed",
            to_dict=lambda: {
                "outcome": "completed",
                "counts": {
                    "pulled": 0,
                    "pushed": 1,
                    "unchanged": 0,
                    "conflicts": 0,
                    "issues": 0,
                },
            },
        )

    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(sync_cli, "run_sync", run_sync)
    monkeypatch.setattr(
        sync_cli,
        "get_settings",
        lambda: SimpleNamespace(auto_project_transitions=True),
    )
    args = _args(
        tmp_path,
        project_key=[" /repo/first ", "/repo/first"],
        thread_id=[" Thread/One ", "Thread/One"],
        no_auto_transitions=True,
    )

    exit_code = sync_cli.handle_sync_run(args, load_session_data)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[0] == ("load", [tmp_path / "sessions"], False)
    assert calls[1][0] == "run"
    assert calls[1][1]["data"] is data
    assert calls[1][1]["project_keys"] == ["/repo/first"]
    assert calls[1][1]["thread_ids"] == ["Thread/One"]
    assert captured.err.splitlines()[0] == '{"type":"sync_progress","phase":"scanning"}'
    assert json.loads(captured.out)["outcome"] == "completed"


def test_sync_commands_reject_empty_selector_union(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_module.main(
        ["sync", "status", "--sync-dir", str(tmp_path / "sync"), "--json"]
    )

    assert exit_code == 2
    assert (
        capsys.readouterr().err.strip()
        == "codex-usage: Select at least one project key or thread id for sync."
    )


def test_sync_status_uses_noncreating_default_path_and_returns_zero_for_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    default_sessions = tmp_path / "codex" / "sessions"
    data = object()
    calls: list[tuple[object, ...]] = []

    def load_session_data(paths: list[Path], *, auto_transitions: bool) -> object:
        calls.append(("load", paths, auto_transitions))
        return data

    def sync_status(**kwargs) -> SimpleNamespace:
        calls.append(("status", kwargs))
        return SimpleNamespace(
            to_dict=lambda: {
                "threads": [],
                "issues": [
                    {"code": "legacy_sync_layout", "message": "legacy", "thread_id": ""}
                ],
            }
        )

    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [default_sessions]
    )
    monkeypatch.setattr(sync_cli, "sync_status", sync_status)
    monkeypatch.setattr(
        sync_cli,
        "get_settings",
        lambda: SimpleNamespace(auto_project_transitions=True),
    )

    exit_code = sync_cli.handle_sync_status(
        _args(tmp_path, project_key=["/repo/first"], thread_id=None),
        load_session_data,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[0] == ("load", [default_sessions], True)
    assert calls[1][0] == "status"
    assert calls[1][1]["data"] is data
    assert not default_sessions.exists()
    assert captured.err.splitlines()[0] == '{"type":"sync_progress","phase":"scanning"}'
    assert json.loads(captured.out)["issues"][0]["code"] == "legacy_sync_layout"


def test_sync_run_returns_two_and_one_human_summary_for_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli,
        "run_sync",
        lambda **kwargs: SimpleNamespace(
            outcome="conflict",
            to_dict=lambda: {"outcome": "conflict", "counts": {}},
        ),
    )
    args = _args(tmp_path, project_key=None, thread_id=["thread-1"], json=False)

    exit_code = sync_cli.handle_sync_run(args, lambda *args, **kwargs: object())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert len(captured.out.splitlines()) == 1
    assert not captured.out.startswith("{")


def test_normalize_thread_ids_preserves_case_and_slashes() -> None:
    thread_ids = normalize_thread_ids(
        [" Owner/Repo ", "Owner/Repo", "owner/repo", "thread-1"]
    )

    assert thread_ids == ["Owner/Repo", "owner/repo", "thread-1"]


def _args(tmp_path: Path, **overrides) -> Namespace:
    values = {
        "sync_dir": tmp_path / "sync",
        "project_key": None,
        "thread_id": None,
        "machine_id": "machine-a",
        "no_auto_transitions": False,
        "json": True,
    }
    values.update(overrides)
    return Namespace(**values)


def _run_cli(
    args: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", *args],
        check=True,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _write_session(path: Path, session_id: str, cwd: str, total: int) -> None:
    usage = {
        "input_tokens": total,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }
    events = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": cwd,
            },
        },
        {
            "timestamp": "2026-04-29T10:00:01Z",
            "type": "turn_context",
            "payload": {"turn_id": f"turn-{session_id}", "model": "gpt-5.5"},
        },
        {
            "timestamp": "2026-04-29T10:00:02Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        },
    ]
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
