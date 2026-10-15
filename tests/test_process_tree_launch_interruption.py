"""Windows blocked-controller ownership survives catchable launch cancellation."""
import pytest

from codex_usage import process_tree, windows_job
from test_process_tree_job_ownership import ControllerProcess, FakeJobApi, RecordingJob


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(143)])
@pytest.mark.parametrize("stage", ["popen", "assign", "release", "released"])
def test_windows_launch_cancellation_releases_all_acquired_ownership(monkeypatch, tmp_path, error, stage):
    events = []
    child = ControllerProcess(events)
    job = RecordingJob(events, assignment_error=error if stage == "assign" else None)
    monkeypatch.setattr(process_tree, "WindowsJob", lambda: job)
    def popen(*args, **kwargs):
        if stage == "popen":
            raise error
        return child
    monkeypatch.setattr(process_tree.subprocess, "Popen", popen)
    release = process_tree._release_windows_controller
    if stage in ("release", "released"):
        def cancelled(process):
            if stage == "released":
                release(process)
            raise error
        monkeypatch.setattr(process_tree, "_release_windows_controller", cancelled)
    with pytest.raises(type(error)) as caught:
        process_tree.run_process_tree(["owned-synthetic-child"], environment={}, cwd=tmp_path,
            timeout_seconds=120, platform_name="nt")
    assert caught.value is error
    assert events.count("job-close") == 1
    if stage != "popen":
        assert "gate-close" in events
        assert events.count("job-terminate") == 1
        assert child.communicate_calls > 0
        assert child.returncode == -9
    if stage == "assign":
        assert child.kill_calls == 1
        assert "release:1" not in events
    if stage == "released":
        assert events.index("release:1") < events.index("job-terminate")


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(143)])
def test_cancelled_job_configuration_closes_the_acquired_native_handle(error):
    class CancelledApi(FakeJobApi):
        def set_kill_on_close(self, handle):
            super().set_kill_on_close(handle)
            raise error
    api = CancelledApi()
    with pytest.raises(type(error)) as caught:
        windows_job.WindowsJob(api=api)
    assert caught.value is error
    assert api.calls == [("create",), ("limit", 91), ("close", 91)]


@pytest.mark.parametrize("fault", ["popen-close", "released-close", "released-terminate"])
def test_launch_cleanup_failure_is_explicit_and_chains_the_original_cancellation(monkeypatch, tmp_path, fault):
    events = []
    error = SystemExit(143)
    child = ControllerProcess(events)
    job = RecordingJob(events)
    def fails():
        raise OSError("injected cleanup failure")
    monkeypatch.setattr(job, "terminate" if fault.endswith("terminate") else "close", fails)
    monkeypatch.setattr(process_tree, "WindowsJob", lambda: job)
    def popen(*args, **kwargs):
        if fault == "popen-close":
            raise error
        return child
    monkeypatch.setattr(process_tree.subprocess, "Popen", popen)
    release = process_tree._release_windows_controller
    def cancelled(process):
        release(process)
        raise error
    monkeypatch.setattr(process_tree, "_release_windows_controller", cancelled)
    with pytest.raises(process_tree.ProcessTreeCleanupError) as caught:
        process_tree.run_process_tree(["owned-synthetic-child"], environment={}, cwd=tmp_path,
            timeout_seconds=120, platform_name="nt")
    assert caught.value.__cause__ is error
    assert any("Job Object" in failure for failure in caught.value.failures)
