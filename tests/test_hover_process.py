"""Only a bounded owned-tree completion can become execution evidence."""
import subprocess
import signal
from pathlib import Path

import pytest

from hover_measurement_fixture import PROCESS
from release_tooling_support import load_tool

process = load_tool("verification.hover_process")


def test_owned_tree_implementation_is_in_the_trusted_execution_closure():
    policy = load_tool("release.policy")
    assert {"src/codex_usage/" + name for name in
        ("process_tree.py", "windows_job.py", "windows_job_controller.py")} <= set(policy.contract_files())


@pytest.mark.parametrize("seconds,returncode", [(1., 0), (600., 0), (601., 0), (1., 7)])
def test_deadline_includes_launch_and_completion_and_rejects_nonzero_exit(monkeypatch, capsys, seconds, returncode):
    ticks = iter((0., seconds))
    monkeypatch.setattr(process, "perf_counter", lambda: next(ticks))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode, "child output", "child stderr")
    monkeypatch.setattr(process, "run_process_tree", run)
    command, env, cwd = ["synthetic-owned-child"], {"synthetic": "only"}, Path("synthetic")
    if seconds >= 600 or returncode:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            process.run_hover(command, environment=env, cwd=cwd)
    else:
        assert process.run_hover(command, environment=env, cwd=cwd) == dict(PROCESS, seconds=seconds)
    assert calls == [(command, {"environment": env, "cwd": cwd, "timeout_seconds": 600})]
    captured = capsys.readouterr()
    assert captured.out == "child output" and captured.err == "child stderr"


def test_timeout_from_owned_tree_supervisor_cannot_become_success(monkeypatch):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 600)
    monkeypatch.setattr(process, "run_process_tree", timed_out)
    with pytest.raises(subprocess.TimeoutExpired):
        process.run_hover(["synthetic-owned-child"], environment={}, cwd=Path("synthetic"))


def test_termination_uses_shared_cleanup_path_and_restores_original_handler(monkeypatch):
    previous = signal.getsignal(signal.SIGTERM)
    def cancelled(*args, **kwargs):
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        handler(signal.SIGTERM, None)
    monkeypatch.setattr(process, "run_process_tree", cancelled)
    with pytest.raises(SystemExit) as caught:
        process.run_hover(["synthetic-owned-child"], environment={}, cwd=Path("synthetic"))
    assert caught.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) is previous


@pytest.mark.parametrize("fault", ["schema", "limit", "status", "ownership", "extra", "bool", "nan", "inf"])
def test_missing_or_forged_process_contract_is_rejected(fault):
    value = dict(PROCESS)
    field, replacement = {"schema": ("schema", True), "limit": ("limit_seconds", 601),
        "status": ("status", "timed out"), "ownership": ("ownership", "signal alarm"),
        "extra": ("ignore_timeout", True), "bool": ("seconds", False),
        "nan": ("seconds", float("nan")), "inf": ("seconds", float("inf"))}[fault]
    value[field] = replacement
    with pytest.raises(ValueError):
        process.validate_process(value)
