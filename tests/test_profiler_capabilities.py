"""Profiler discovery is bounded, content-free and never attaches to a process."""
import json
from types import SimpleNamespace

import pytest

from release_tooling_support import load_tool

capabilities = load_tool("probes.profiler_capabilities")


def test_preflight_refuses_local_host_before_files_or_commands(monkeypatch, tmp_path):
    def refuse():
        raise ValueError("ephemeral diagnostic only")
    monkeypatch.setattr(capabilities, "require_ephemeral_host", refuse)
    monkeypatch.setattr(capabilities.subprocess, "run", lambda *_a, **_k: pytest.fail("No commands"))
    destination = tmp_path / "absent"
    with pytest.raises(ValueError, match="ephemeral"):
        capabilities.collect(destination)
    assert not destination.exists()


def test_preflight_collects_only_allowlisted_help_without_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "require_ephemeral_host", lambda: None)
    monkeypatch.setenv("GH_TOKEN", "must-not-reach-profiler")
    monkeypatch.setenv("VSCE_PAT", "must-not-reach-profiler")
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert "GH_TOKEN" not in kwargs["env"] and "VSCE_PAT" not in kwargs["env"]
        assert kwargs["timeout"] == 10 and kwargs["check"] is False
        return SimpleNamespace(stdout="tool help", stderr="", returncode=0)
    monkeypatch.setattr(capabilities.subprocess, "run", run)
    result = capabilities.collect(tmp_path)
    assert result["status"] == "available" and result["process_attachment"] is False
    assert commands == list(capabilities.COMMANDS.values())
    assert all(command[2:] != ("record",) for command in commands)
    assert (tmp_path / "record-help.txt").read_text() == "tool help"
    assert json.loads((tmp_path / "capabilities.json").read_text()) == result


@pytest.mark.parametrize("fault", ("absent", "timeout", "oversize"))
def test_preflight_unavailability_never_substitutes_another_tool(monkeypatch, tmp_path, fault):
    monkeypatch.setattr(capabilities, "require_ephemeral_host", lambda: None)
    commands = []
    def run(command, **_kwargs):
        commands.append(command)
        if fault == "timeout":
            raise capabilities.subprocess.TimeoutExpired(command, 10)
        return SimpleNamespace(returncode=72 if fault == "absent" else 0,
            stdout="x" * (capabilities.OUTPUT_LIMIT + 1) if fault == "oversize" else "missing",
            stderr="")
    monkeypatch.setattr(capabilities.subprocess, "run", run)
    result = capabilities.collect(tmp_path)
    assert result["status"] == "unavailable"
    assert result["diagnostic_only"] is True and result["process_attachment"] is False
    if fault in ("absent", "timeout"):
        assert len(commands) == 1
    assert all(path.stat().st_size <= capabilities.OUTPUT_LIMIT
        for path in tmp_path.glob("*.txt"))
