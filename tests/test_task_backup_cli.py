from __future__ import annotations

import json
from pathlib import Path

from codex_usage import cli


def test_storage_backup_and_verify_cli_emit_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / ".codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    task = sessions / "root.jsonl"
    task.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": "root", "cwd": "/project/example"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(tmp_path / "cache"))
    output = tmp_path / "root.codex-task-backup"

    assert cli.main(
        [
            "storage",
            "backup",
            "--tree-id",
            "root",
            "--output",
            str(output),
            "--compression",
            "balanced",
            "--json",
            "--progress-json",
        ]
    ) == 0
    backup_output = capsys.readouterr()
    backup_payload = json.loads(backup_output.out)
    progress = [json.loads(line) for line in backup_output.err.splitlines()]
    assert backup_payload["recovery_ready"] is True
    assert {event["phase"] for event in progress} == {
        "preparing",
        "compressing",
        "verifying",
    }

    assert cli.main(["storage", "verify", str(output), "--json"]) == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["archive_sha256"] == backup_payload["archive_sha256"]


def test_storage_snapshot_uses_storage_only_context(monkeypatch, tmp_path: Path, capsys) -> None:
    home = tmp_path / ".codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "root.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": "root"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        cli,
        "load_session_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("usage parser called")),
    )

    assert cli.main(["storage", "snapshot", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_trees"][0]["root_task_id"] == "root"
