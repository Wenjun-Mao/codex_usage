from __future__ import annotations

import subprocess
from pathlib import Path

from codex_usage.codex_registration import register_codex_tasks


def test_registration_process_receives_active_codex_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    def fail_to_start(*_args, **kwargs):
        captured.update(kwargs["env"])
        raise OSError("expected test failure")

    monkeypatch.setattr(subprocess, "Popen", fail_to_start)
    home = tmp_path / "custom-codex"

    result = register_codex_tasks(
        ("task-1",),
        codex_home=home,
        candidates=("codex-test",),
    )

    assert captured["CODEX_HOME"] == str(home.resolve())
    assert result.registered_task_ids == ()
    assert "expected test failure" in result.failures[0].message
