from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_schema import open_ledger
from codex_usage.parallel.execution import SERIAL_FALLBACK_WARNING
from codex_usage.session_cache import refresh_cached_session_data


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_collector_diverts_workers_before_application_imports():
    path = ROOT / "src/codex_usage/agent_main.py"
    tree = ast.parse(path.read_text())
    assert not any(isinstance(node, ast.ImportFrom) and
                   (node.module or "").startswith("codex_usage.") for node in tree.body)
    guard = next(node for node in tree.body if isinstance(node, ast.If))
    calls = [ast.unparse(node.func) for node in ast.walk(guard) if isinstance(node, ast.Call)]
    assert calls[0] == "multiprocessing.freeze_support"
    assert calls.index("multiprocessing.freeze_support") < calls.index("main")
    result = subprocess.run([sys.executable, "-c",
        "import sys; import codex_usage.agent_main; "
        "assert 'codex_usage.agent_runtime' not in sys.modules"],
        cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def write_sources(home):
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    for index in range(2):
        rows = [
            {"type": "session_meta", "payload": {"id": f"task-{index}"}},
            {"type": "event_msg", "timestamp": "2026-10-16T12:00:00Z",
             "payload": {"type": "token_count", "info": {"total_token_usage":
                {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}}}},
        ]
        (sessions / f"{index}.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
    return sessions


def fail_pool(**kwargs):
    raise OSError("PRIVATE path must not enter audit")


def test_refresh_only_propagates_infrastructure_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("codex_usage.parallel.execution.os.process_cpu_count", lambda: 2)
    sessions = write_sources(tmp_path)
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    pool = Mock(side_effect=fail_pool)
    monkeypatch.setattr("codex_usage.parallel.execution.ProcessPoolExecutor", pool)
    with pytest.warns(RuntimeWarning, match=SERIAL_FALLBACK_WARNING):
        result = refresh_cached_session_data([sessions], cache_database_path=db,
            max_workers=2, auto_transitions=False, refresh_storage_metadata=False)
    assert result.stats.worker_serial_fallbacks == 1
    assert result.stats.worker_infrastructure_errors == 1
    assert result.stats.file_errors == 0
    pool.assert_called_once()


def test_capture_audit_is_opt_in_bounded_and_content_free(tmp_path, monkeypatch):
    monkeypatch.setattr("codex_usage.parallel.execution.os.process_cpu_count", lambda: 2)
    write_sources(tmp_path)
    monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", lambda *args: None)
    pool = Mock(side_effect=fail_pool)
    monkeypatch.setattr("codex_usage.parallel.execution.ProcessPoolExecutor", pool)
    audit = tmp_path / "audit.json"
    with pytest.warns(RuntimeWarning, match=SERIAL_FALLBACK_WARNING):
        result = capture_once(tmp_path, request_kind="manual", max_workers=2,
                              auto_transitions=False, audit_path=audit)
    assert result.outcome == "success", result.error
    assert result.stats.worker_serial_fallbacks == 1
    pool.assert_called_once()
    payload = json.loads(audit.read_text())
    assert payload["capture_run_id"] == result.run_id
    assert payload["usage_run"]["used_serial_fallback"]
    assert payload["usage_run"]["infrastructure_error"] == "present"
    assert "PRIVATE" not in audit.read_text()
    assert str(tmp_path) not in audit.read_text()
    if sys.platform != "win32":
        assert audit.stat().st_mode & 0o077 == 0
    unchanged = capture_once(tmp_path, request_kind="manual", max_workers=2,
                             auto_transitions=False, audit_path=audit)
    payload = json.loads(audit.read_text())
    assert payload["capture_run_id"] == unchanged.run_id
    assert payload["usage_run"]["span_count"] == 0
    assert not payload["usage_run"]["used_serial_fallback"]


def test_file_error_is_not_an_infrastructure_fallback(tmp_path):
    sessions = write_sources(tmp_path)
    (sessions / "0.jsonl").write_bytes(b"\xff\n")
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    result = refresh_cached_session_data([sessions], cache_database_path=db,
        max_workers=1, auto_transitions=False, refresh_storage_metadata=False)
    assert result.stats.file_errors == 1
    assert result.stats.worker_serial_fallbacks == 0
    assert result.stats.worker_infrastructure_errors == 0
