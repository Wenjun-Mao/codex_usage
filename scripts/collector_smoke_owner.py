"""One outer ownership boundary for the smoke driver and all its descendants."""
import json
import os
from pathlib import Path
import subprocess
import time

from codex_usage.process_tree import _cleanup_failed_process, _launch_owned_process


def posix_running(pid):
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True, text=True, timeout=1)
    state = result.stdout.strip()
    return bool(state) and state[0] not in "ZX"


def run_driver(command, *, environment, cwd, timeout_seconds=120, stop_after_state=None):
    process, job = _launch_owned_process(command, environment=environment, cwd=cwd, platform_name=os.name)
    handles, handle, observed = None, None, None
    try:
        if stop_after_state is not None:
            deadline = time.monotonic()+90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("cleanup driver exited before its owned collector was observed")
                try:
                    observed = json.loads(Path(stop_after_state).read_text())["pid"]
                except (OSError, json.JSONDecodeError):
                    time.sleep(.02)
                    continue
                assert type(observed) is int and observed > 0 and observed != process.pid
                if os.name == "nt":
                    from packaged_windows_process_tree_smoke import _WindowsProcesses
                    handles = _WindowsProcesses()
                    handle = handles.open(observed)
                    assert handle is not None and not handles.is_exited(handle)
                else:
                    assert posix_running(observed), "collector was not alive before forced timeout"
                break
            else:
                raise TimeoutError("cleanup collector observation deadline exceeded")
            try:
                process.communicate(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
            else:
                raise AssertionError("forced timeout did not occur")
        else:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        # Also kill remaining descendants after a driver exits unsuccessfully.
        # The driver never detaches its collector from this group/Job.
        try:
            _cleanup_failed_process(process, platform_name=os.name, windows_job=job)
            if observed is not None:
                if handles and handle is not None:
                    assert handles.wait_exited(handle, 2), "owned collector survived timeout"
                elif handles is None:
                    deadline = time.monotonic()+2
                    while time.monotonic() < deadline:
                        if not posix_running(observed):
                            break
                        time.sleep(.02)
                    else:
                        raise AssertionError("owned collector survived timeout")
        finally:
            if handles and handle is not None:
                handles.close(handle)
    return {"forced_timeout": True, "collector_observed_alive": True, "collector_observed_exited": True}
