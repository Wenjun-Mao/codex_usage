"""A failed or interrupted attempt cannot leave a reusable process receipt."""
import json
import subprocess

import pytest

from hover_measurement_fixture import PROCESS
from qualification_fixture import visual_evidence
from release_tooling_support import load_tool

runner = load_tool("run_visual_suite")


@pytest.mark.parametrize("fault", [None, "timeout", "nonzero", "interrupted", "incomplete"])
def test_stale_proof_is_removed_before_launch_and_replaced_only_after_complete_success(
    monkeypatch, tmp_path, fault,
):
    directory = tmp_path / "hover"
    directory.mkdir()
    receipt = directory / "process.json"
    receipt.write_text("stale proof")
    monkeypatch.setattr(runner.sys, "argv", ["run_visual_suite.py", "hover", "--output", str(tmp_path)])
    calls = []
    def owned(command, **kwargs):
        calls.append((command, kwargs))
        assert not receipt.exists()
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 600)
        if fault == "nonzero":
            raise subprocess.CalledProcessError(9, command)
        if fault == "interrupted":
            raise KeyboardInterrupt()
        evidence = visual_evidence("hover")
        if fault == "incomplete":
            evidence["completed"].pop()
        (directory / "verification.json").write_text(json.dumps(evidence))
        return dict(PROCESS)
    monkeypatch.setattr(runner, "run_hover", owned)
    if fault:
        with pytest.raises((subprocess.SubprocessError, KeyboardInterrupt, ValueError)):
            runner.main()
        assert not receipt.exists()
    else:
        runner.main()
        assert json.loads(receipt.read_text()) == PROCESS
    assert len(calls) == 1
    assert calls[0][0][-2:] == ["--output", str(directory)]
