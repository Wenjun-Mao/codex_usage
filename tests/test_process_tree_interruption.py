"""Catchable cancellation must terminate owned descendants before propagating."""
import signal

import pytest

from codex_usage import process_tree
from test_process_tree import RecordingWindowsJob, TimedOutProcess, assert_bounded_cleanup_timeouts


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(143), RuntimeError("transport failed")])
@pytest.mark.parametrize("platform", ["posix", "nt"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_interruption_cleans_the_owned_tree_then_preserves_original_cause(
    monkeypatch, tmp_path, error, platform, cleanup_fails,
):
    class InterruptedProcess(TimedOutProcess):
        def communicate(self, timeout=None):
            if not self.communicate_timeouts:
                self.communicate_timeouts.append(timeout)
                raise error
            return super().communicate(timeout)
    process = InterruptedProcess()
    job = RecordingWindowsJob(terminate_error=cleanup_fails) if platform == "nt" else None
    monkeypatch.setattr(process_tree, "_launch_owned_process", lambda *a, **kw: (process, job))
    groups = []
    def killpg(pid, sig):
        groups.append((pid, sig))
        if cleanup_fails:
            raise OSError("killpg denied")
    monkeypatch.setattr(process_tree.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(process_tree.signal, "SIGKILL", 9, raising=False)
    expected = process_tree.ProcessTreeCleanupError if cleanup_fails else type(error)
    with pytest.raises(expected) as caught:
        process_tree.run_process_tree(["owned-synthetic-child"], environment={}, cwd=tmp_path,
            timeout_seconds=120, platform_name=platform)
    if cleanup_fails:
        assert caught.value.__cause__ is error
        assert process.kill_calls == 1
    else:
        assert caught.value is error
    if platform == "posix":
        assert groups == [(process.pid, signal.SIGKILL)]
    else:
        assert job.terminate_calls == job.close_calls == 1
    assert_bounded_cleanup_timeouts(process)
