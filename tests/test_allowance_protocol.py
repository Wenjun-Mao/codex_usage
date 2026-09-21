import os
import sys
from pathlib import Path

import pytest

from codex_usage.allowance_models import quota_observations, rollout_observations
from codex_usage.app_server_rpc import AppServerRpc, RpcError


def bucket(used=31):
    return {"limitId": "codex", "planType": "pro", "primary": {
        "usedPercent": used, "windowDurationMins": 10080, "resetsAt": 2000000000,
    }}


def test_allowlist_multi_bucket_and_missing_plan():
    payload = {"accountId": "private-account", "rateLimitsByLimitId": {
        "codex": bucket(), "other": {"secondary": bucket()["primary"]},
    }, "rateLimitResetCredits": {"availableCount": 2, "credits": [{"id": "private"}]}}
    points = quota_observations(payload, "2026-09-21T00:00:00Z")
    assert len(points) == 2
    assert points[0].plan == "pro" and points[1].plan == ""
    assert points[1].limit_id == "other" and points[1].reset_credits == 2
    assert "private" not in str(points)


@pytest.mark.parametrize("invalid", [-1, 101, float("nan"), float("inf"), True, "50", None])
def test_malformed_percent_is_not_zero(invalid):
    assert quota_observations(bucket(invalid), "2026-09-21T00:00:00Z") == ()


def test_rollout_content_is_not_retained():
    row = {"timestamp": "2026-09-21T00:00:00Z", "type": "event_msg", "payload": {
        "type": "token_count", "rate_limits": {"plan_type": "plus", "primary": {
            "used_percent": 42, "window_minutes": 333, "resets_at": 2000000000}},
        "prompt": "PRIVATE CONTENT", "info": {"secret": "PRIVATE CONTENT"}}}
    points = rollout_observations(row)
    assert points[0].duration_minutes == 333
    assert "PRIVATE" not in str(points)


def fake_server(tmp_path: Path, mode="normal"):
    script = tmp_path / "codex"
    script.write_text(f'''#!{sys.executable}
import json, os, sys, time
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request: continue
    if {mode!r} == "timeout": time.sleep(10)
    if {mode!r} == "malformed":
        print("[]", flush=True)
        continue
    result = {{"home": os.environ.get("CODEX_HOME"), "method": request["method"]}}
    print(json.dumps({{"method": "ignored/notification", "params": {{}}}}), flush=True)
    print(json.dumps({{"id": request["id"], "result": result}}), flush=True)
''')
    script.chmod(0o700)
    return str(script)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture; Windows uses mocked Popen contract")
def test_rpc_custom_home_and_process_cleanup(tmp_path):
    with AppServerRpc(fake_server(tmp_path), tmp_path / "custom", timeout=2) as rpc:
        result = rpc.call("account/read", {"refreshToken": False})
        process = rpc.process
        assert result["home"] == str(tmp_path / "custom")
        assert result["method"] == "account/read"
    assert process.poll() is not None
    assert all(not thread.is_alive() for thread in rpc.threads)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
@pytest.mark.parametrize("mode", ["timeout", "malformed"])
def test_rpc_failure_closes_process(tmp_path, mode):
    rpc = AppServerRpc(fake_server(tmp_path, mode), tmp_path, timeout=.1)
    with pytest.raises(RpcError):
        with rpc:
            pass
    assert rpc.process.poll() is not None


def test_windows_launch_environment_and_cleanup_contract(tmp_path, monkeypatch):
    import io
    import codex_usage.app_server_rpc as module

    launched = []
    stopped = []

    class Process:
        pid = 123
        stdin = io.BytesIO()
        stdout = io.BytesIO(b'{"id":1,"result":{}}\n{"id":2,"result":{"ok":true}}\n')

        def wait(self, timeout):
            return 0

    class Job:
        def assign(self, pid):
            assert pid == 123

        def close(self):
            stopped.append(process)

    process = Process()
    monkeypatch.setattr(module, "WindowsJob", Job)
    monkeypatch.setattr(module, "windows_runtime", lambda: True)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **kw: launched.append((a, kw)) or process)
    monkeypatch.setattr(module, "_stop_process_tree", stopped.append)
    with AppServerRpc("codex.exe", tmp_path) as rpc:
        assert rpc.call("account/read") == {"ok": True}
    assert launched[0][1]["creationflags"] == 512
    assert launched[0][1]["start_new_session"] is False
    assert launched[0][1]["env"]["CODEX_HOME"] == str(tmp_path)
    assert stopped == [process]
    assert process.stdout.closed and process.stdin.closed


def test_probe_uses_only_official_metadata_methods_and_retains_no_identity(tmp_path, monkeypatch):
    import codex_usage.allowance_probe as module
    calls = []

    class Rpc:
        def __init__(self, executable, codex_home, timeout):
            assert codex_home == tmp_path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def call(self, method, params):
            calls.append((method, params))
            return {
                "account/read": {"account": {"planType": "pro", "email": "PRIVATE"}},
                "account/rateLimits/read": {"rateLimits": bucket(), "accountId": "PRIVATE"},
                "account/usage/read": {"summary": {"lifetimeTokens": 123}, "secret": "PRIVATE"},
            }[method]

    monkeypatch.setattr(module, "AppServerRpc", Rpc)
    monkeypatch.setattr(module, "discover_codex_executables", lambda: ("codex",))
    read = module.probe_allowance(tmp_path)
    assert [method for method, _ in calls] == ["account/read", "account/rateLimits/read", "account/usage/read"]
    assert calls[0][1] == {"refreshToken": False}
    assert read.plan == "pro" and read.lifetime_tokens == 123
    assert "PRIVATE" not in repr(read)
