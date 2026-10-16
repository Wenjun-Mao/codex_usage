import json
import os
import subprocess
import sys

import pytest

from release_tooling_support import load_tool


owner = load_tool("collector_smoke_owner")


def test_outer_timeout_owns_nested_collector_and_observes_exit(tmp_path):
    state = tmp_path / "state.json"
    program = (
        "import json,subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        f"Path({str(state)!r}).write_text(json.dumps(dict(pid=child.pid))); time.sleep(120)"
    )
    result = owner.run_driver([sys.executable, "-c", program], environment=dict(os.environ),
                             cwd=tmp_path, stop_after_state=state)
    assert result == {"forced_timeout": True, "collector_observed_alive": True, "collector_observed_exited": True}
    assert json.loads(state.read_text())["pid"] > 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX session inheritance assertion")
def test_driver_and_nested_collector_do_not_create_separate_groups(tmp_path):
    program = (
        "import os,subprocess,sys; "
        "assert os.getpgrp()==os.getpid(); "
        "child=subprocess.run([sys.executable,'-c','import os; print(os.getpgrp())'],capture_output=True,text=True); "
        "assert int(child.stdout)==os.getpgrp(); print('shared')"
    )
    result = owner.run_driver([sys.executable, "-c", program], environment=dict(os.environ), cwd=tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == "shared"


def test_timeout_cleanup_preserves_timeout_failure(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        owner.run_driver([sys.executable, "-c", "import time; time.sleep(120)"],
                         environment=dict(os.environ), cwd=tmp_path, timeout_seconds=.1)


@pytest.mark.skipif(os.name != "posix", reason="POSIX zombie observation")
def test_already_exited_collector_cannot_prove_timeout_cleanup(tmp_path):
    state = tmp_path / "state.json"
    program = (
        "import json,subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','pass']); child.wait(); "
        f"Path({str(state)!r}).write_text(json.dumps(dict(pid=child.pid))); time.sleep(120)"
    )
    with pytest.raises(AssertionError, match="not alive"):
        owner.run_driver([sys.executable, "-c", program], environment=dict(os.environ),
                         cwd=tmp_path, stop_after_state=state)


@pytest.mark.parametrize("state,expected", [("Z", False), ("ZX", False), ("", False), ("R", True), ("S", True)])
def test_posix_observation_does_not_treat_zombie_as_alive(monkeypatch, state, expected):
    monkeypatch.setattr(owner.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, state, ""))
    assert owner.posix_running(123) is expected
