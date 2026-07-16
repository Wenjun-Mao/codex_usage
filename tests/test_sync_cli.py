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
from codex_usage.sync_cli import _sync_session_dirs


def test_cli_sync_push_and_pull_are_manual_directional_commands(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    source_day = source_home / "sessions" / "2026" / "04" / "29"
    source_day.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _write_session(source_day / "thread-1.jsonl", "thread-1", str(project), 100)
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
            "push",
            "--sync-dir",
            str(sync_dir),
            "--thread-id",
            "thread-1",
            "--json",
        ],
        env={"CODEX_HOME": str(source_home)},
    )

    assert json.loads(pushed.stdout)["outcome"] == "completed"
    assert json.loads(pushed.stdout)["counts"]["pushed"] == 1
    assert '"phase":"scanning"' in pushed.stderr.replace(" ", "")
    assert '"phase":"pulling"' not in pushed.stderr.replace(" ", "")

    target_home = tmp_path / "target"
    (target_home / "archived_sessions").mkdir(parents=True)
    (target_home / ".codex-global-state.json").write_text(
        json.dumps({"electron-saved-workspace-roots": [str(project)]}),
        encoding="utf-8",
    )
    pulled = _run_cli(
        [
            "sync",
            "pull",
            "--sync-dir",
            str(sync_dir),
            "--thread-id",
            "thread-1",
            "--json",
        ],
        env={"CODEX_HOME": str(target_home)},
    )

    assert json.loads(pulled.stdout)["counts"]["pulled"] == 1
    assert len(list((target_home / "sessions").rglob("*.jsonl"))) == 1
    assert not list((target_home / "archived_sessions").rglob("*.jsonl"))


def test_sync_execution_root_creates_active_sessions_when_only_archive_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex"
    archived_sessions = codex_home / "archived_sessions"
    archived_sessions.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    session_dirs = _sync_session_dirs(create=True)

    assert session_dirs == [codex_home / "sessions"]
    assert (codex_home / "sessions").is_dir()
    assert archived_sessions not in session_dirs


def test_sync_status_root_returns_active_sessions_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex"
    archived_sessions = codex_home / "archived_sessions"
    archived_sessions.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    session_dirs = _sync_session_dirs(create=False)

    assert session_dirs == [codex_home / "sessions"]
    assert not (codex_home / "sessions").exists()
    assert archived_sessions not in session_dirs


def test_cli_sync_help_exposes_manual_directional_commands_and_status() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", "sync", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "{inventory,pull,push,status}" in result.stdout
    assert "run" not in result.stdout
    assert "import" not in result.stdout
    assert "export" not in result.stdout
    assert "--conflict-policy" not in result.stdout


def test_sync_inventory_loads_local_data_once_and_prints_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = object()
    calls: list[tuple[object, ...]] = []
    expected = SimpleNamespace(
        to_dict=lambda: {"inventory_version": 1, "projects": [], "issues": []}
    )

    def load(paths: list[Path], *, auto_transitions: bool) -> object:
        calls.append((tuple(paths), auto_transitions))
        return data

    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli, "load_sync_selection_inventory", lambda value, path: expected
    )

    exit_code = sync_cli.handle_sync_inventory(_args(tmp_path), load)

    assert exit_code == 0
    assert calls == [((tmp_path / "sessions",), True)]
    assert json.loads(capsys.readouterr().out) == expected.to_dict()


def test_cli_sync_inventory_lists_one_local_task_from_an_empty_remote_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codex_home = tmp_path / "codex"
    session_day = codex_home / "sessions" / "2026" / "04" / "29"
    session_day.mkdir(parents=True)
    _write_session(session_day / "thread-1.jsonl", "thread-1", "/repo/first", 100)
    (codex_home / "session_index.jsonl").write_text(
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
    sync_dir.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    exit_code = cli_module.main(
        ["sync", "inventory", "--sync-dir", str(sync_dir), "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["inventory_version"] == 2
    assert payload["issues"] == []
    assert len(payload["projects"]) == 1
    assert payload["projects"][0]["project_key"] == "/repo/first"
    assert payload["projects"][0]["tasks"][0]["thread_id"] == "thread-1"
    assert payload["projects"][0]["tasks"][0]["title"] == "First thread"
    assert payload["projects"][0]["tasks"][0]["availability"] == "local"
    assert list(sync_dir.iterdir()) == []


def test_sync_inventory_prints_one_human_summary_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = SimpleNamespace(
        to_dict=lambda: {
            "inventory_version": 1,
            "projects": [
                {"tasks": [{"thread_id": "one"}, {"thread_id": "two"}]},
                {"tasks": [{"thread_id": "three"}]},
            ],
            "issues": [{"code": "notice"}],
        }
    )
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli, "load_sync_selection_inventory", lambda data, path: inventory
    )

    exit_code = sync_cli.handle_sync_inventory(
        _args(tmp_path, json=False), lambda *args, **kwargs: object()
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "Sync inventory: 2 projects, 3 tasks, 1 issues.\n"


def test_sync_push_loads_cache_once_after_scanning_and_passes_normalized_thread_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = object()
    calls: list[tuple[object, ...]] = []

    def load_session_data(paths: list[Path], *, auto_transitions: bool) -> object:
        calls.append(("load", paths, auto_transitions))
        return data

    def push_sync(**kwargs) -> SimpleNamespace:
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
    monkeypatch.setattr(sync_cli, "push_sync", push_sync)
    monkeypatch.setattr(
        sync_cli,
        "get_settings",
        lambda: SimpleNamespace(auto_project_transitions=True),
    )
    args = _args(
        tmp_path,
        thread_id=[" Thread/One ", "Thread/One"],
        no_auto_transitions=True,
    )

    exit_code = sync_cli.handle_sync_push(args, load_session_data)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[0] == ("load", [tmp_path / "sessions"], False)
    assert calls[1][0] == "run"
    assert calls[1][1]["data"] is data
    assert calls[1][1]["thread_ids"] == ("Thread/One",)
    assert "project_keys" not in calls[1][1]
    assert captured.err.splitlines()[0] == '{"type":"sync_progress","phase":"scanning"}'
    assert json.loads(captured.out)["outcome"] == "completed"


def test_sync_pull_calls_directional_runner_without_machine_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    result = SimpleNamespace(
        outcome="completed",
        to_dict=lambda: {"outcome": "completed", "counts": {}},
    )
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli,
        "get_settings",
        lambda: SimpleNamespace(auto_project_transitions=True),
    )
    monkeypatch.setattr(
        sync_cli,
        "pull_sync",
        lambda **kwargs: calls.append(kwargs) or result,
    )

    exit_code = sync_cli.handle_sync_pull(
        _args(tmp_path, thread_id=["thread-1"]),
        lambda *args, **kwargs: object(),
    )

    assert exit_code == 0
    assert calls[0]["thread_ids"] == ("thread-1",)
    assert "machine_id" not in calls[0]


def test_sync_commands_reject_empty_task_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_module.main(
        ["sync", "status", "--sync-dir", str(tmp_path / "sync"), "--json"]
    )

    assert exit_code == 2
    assert (
        capsys.readouterr().err.strip()
        == "codex-usage: Select at least one task with --thread-id for sync."
    )


@pytest.mark.parametrize("sync_command", ["pull", "push", "status"])
def test_sync_execution_commands_reject_project_key(sync_command: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_usage.cli",
            "sync",
            sync_command,
            "--sync-dir",
            str(tmp_path / "sync"),
            "--project-key",
            "/repo/first",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unrecognized arguments: --project-key /repo/first" in result.stderr


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
        _args(tmp_path, thread_id=["thread-1"]),
        load_session_data,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[0] == ("load", [default_sessions], True)
    assert calls[1][0] == "status"
    assert calls[1][1]["data"] is data
    assert calls[1][1]["thread_ids"] == ("thread-1",)
    assert "project_keys" not in calls[1][1]
    assert not default_sessions.exists()
    assert captured.err.splitlines()[0] == '{"type":"sync_progress","phase":"scanning"}'
    assert json.loads(captured.out)["issues"][0]["code"] == "legacy_sync_layout"


def test_sync_push_returns_two_and_one_human_summary_for_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli,
        "push_sync",
        lambda **kwargs: SimpleNamespace(
            outcome="conflict",
            to_dict=lambda: {"outcome": "conflict", "counts": {}},
        ),
    )
    args = _args(tmp_path, thread_id=["thread-1"], json=False)

    exit_code = sync_cli.handle_sync_push(args, lambda *args, **kwargs: object())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert len(captured.out.splitlines()) == 1
    assert not captured.out.startswith("{")


def _args(tmp_path: Path, **overrides) -> Namespace:
    values = {
        "sync_dir": tmp_path / "sync",
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
