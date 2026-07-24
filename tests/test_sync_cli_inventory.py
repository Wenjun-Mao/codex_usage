import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_usage.cli as cli_module
import codex_usage.sync_cli as sync_cli


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
        sync_cli,
        "load_sync_selection_inventory",
        lambda value, path, *, candidate_roots: expected,
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
        sync_cli,
        "load_sync_selection_inventory",
        lambda data, path, *, candidate_roots: inventory,
    )

    exit_code = sync_cli.handle_sync_inventory(
        _args(tmp_path, json=False), lambda *args, **kwargs: object()
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "Sync inventory: 2 projects, 3 tasks, 1 issues.\n"


def _args(tmp_path: Path, **overrides) -> Namespace:
    values = {
        "sync_dir": tmp_path / "sync",
        "thread_id": None,
        "machine_id": "machine-a",
        "project_key": "/repo/first",
        "no_auto_transitions": False,
        "json": True,
    }
    values.update(overrides)
    return Namespace(**values)


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
