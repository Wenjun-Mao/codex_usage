"""Retirement removes execution, never the user's existing transfer data."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path

import pytest

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_runtime import CodexUsageAgent
from codex_usage.agent_settings import AgentSettings, load_agent_settings, save_agent_settings
from codex_usage.cli import main


@pytest.mark.parametrize("operation", ["inventory", "pull", "push", "status"])
def test_retired_cli_commands_fail_before_loading_user_data(operation, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "must-not-exist"))
    with pytest.raises(SystemExit) as stopped:
        main(["sync", operation])
    assert stopped.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("path", ["/v1/transfer/inventory", "/v1/transfer/execute"])
def test_retired_api_routes_reject_without_dispatch_or_file_access(path, tmp_path):
    class NoTransferAgent:
        def __getattr__(self, name):
            raise AssertionError(f"Retired route attempted agent dispatch: {name}")

    server = AgentHttpServer(NoTransferAgent(), token="x" * 40)
    server.start()
    try:
        for method in ("GET", "POST"):
            client = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            client.request(method, path, body=json.dumps({"operation": "import", "sync_dir": str(tmp_path)}),
                           headers={"Authorization": "Bearer " + "x" * 40})
            result = client.getresponse()
            assert result.status == 404
            assert json.loads(result.read()) == {"error": "not found"}
            client.close()
        assert not list(tmp_path.iterdir())
    finally:
        server.stop()


@pytest.mark.parametrize("kind", ["missing", "inaccessible", "symlink"])
def test_saved_transfer_folder_is_inert_and_preserved(kind, tmp_path, monkeypatch):
    home = tmp_path / "codex"
    home.mkdir()
    target = tmp_path / "transfer"
    folder = target
    if kind != "missing":
        target.mkdir()
        (target / "index.json").write_text('{"version":3}', encoding="utf-8")
    if kind == "symlink":
        folder = tmp_path / "transfer-link"
        folder.symlink_to(target, target_is_directory=True)
    settings_file = tmp_path / "settings.json"
    save_agent_settings(AgentSettings(codex_home=str(home), transfer_folder=str(folder)), settings_file)

    def guarded(original):
        def check(path, *args, **kwargs):
            if path == folder or path == target or target in path.parents or folder in path.parents:
                raise AssertionError("Legacy transfer folder was accessed")
            return original(path, *args, **kwargs)
        return check

    with monkeypatch.context() as patch:
        for name in ("stat", "lstat", "resolve", "iterdir", "open"):
            patch.setattr(Path, name, guarded(getattr(Path, name)))
        agent = CodexUsageAgent(settings_file=settings_file)
        try:
            assert not hasattr(agent, "transfer_inventory")
            assert not hasattr(agent, "execute_transfer")
            changed = agent.update_settings({"theme": "night", "transfer_folder": "replacement"})
            assert changed.theme == "night"
            assert changed.transfer_folder == str(folder)
            assert load_agent_settings(settings_file).transfer_folder == str(folder)
        finally:
            agent._lane.close()


def test_remaining_startup_capture_and_reports_preserve_chat_and_transfer_files(tmp_path, monkeypatch):
    from codex_usage import allowance_capture
    from codex_usage.allowance_probe import QuotaRead

    home = tmp_path / "codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    task_id = "00000000-0000-4000-8000-000000000213"
    task = sessions / f"rollout-{task_id}.jsonl"
    task.write_text(json.dumps({"timestamp": "2026-10-22T12:00:00Z", "type": "session_meta",
        "payload": {"id": task_id, "cwd": str(project), "source": "vscode"}}) + "\n", encoding="utf-8")
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    export = transfer / "export.jsonl"
    export.write_bytes(task.read_bytes())
    normalized = os.path.normcase(str(transfer.resolve(strict=False))).replace("\\", "/")
    fingerprint = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    bookkeeping = home / ".codex-sync-state" / fingerprint / "threads" / f"{task_id}.json"
    bookkeeping.parent.mkdir(parents=True)
    bookkeeping.write_text(json.dumps({"sync_version": 2, "thread_id": task_id,
        "sync_dir_fingerprint": fingerprint, "base_sha256": hashlib.sha256(task.read_bytes()).hexdigest(),
        "base_size_bytes": task.stat().st_size, "source_relative_path": task.name}), encoding="utf-8")
    private_state = home / ".codex-global-state.json"
    private_state.write_bytes(b'{"local-projects":{}}')
    index = home / "session_index.jsonl"
    index.write_text(json.dumps({"id": task_id, "thread_name": "Preserved task"}) + "\n", encoding="utf-8")
    private_database = home / "state_5.sqlite"
    import sqlite3
    with sqlite3.connect(private_database) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('preserve')")
    selected = [task, export, bookkeeping, private_state, index, private_database]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
    settings_file = tmp_path / "settings.json"
    save_agent_settings(AgentSettings(codex_home=str(home), transfer_folder=str(transfer),
                                     capture_interval_minutes=None), settings_file)
    monkeypatch.setattr(allowance_capture, "probe_allowance", lambda *_:
                        QuotaRead("2026-10-22T12:00:00+00:00", diagnostics="synthetic"))
    agent = CodexUsageAgent(settings_file=settings_file)
    try:
        agent.start()
        assert agent.capture_now().result(timeout=10).outcome == "success"
        assert 'data-codex-theme="night"' in agent.report(range_name="all", project_keys=[], theme="night").html
        assert agent.storage_snapshot([])["totals"]["physical_file_count"] == 1
        assert agent.export_agent_activity(range_name="all", start_date=None, end_date=None,
                                           project_keys=[])["row_count"] == 0
        agent.update_settings({"theme": "day"})
    finally:
        agent.stop()
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in selected} == before
    assert load_agent_settings(settings_file).transfer_folder == str(transfer)
