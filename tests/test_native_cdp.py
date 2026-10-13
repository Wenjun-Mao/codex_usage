"""Native transport bounds the entire command and correlates asynchronous replies."""
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from release_tooling_support import load_tool

transport = load_tool("native_cdp")


class Session:
    def __init__(self, mode):
        self.mode, self.handlers, self.calls, self.detached = mode, {}, [], False

    def on(self, event, handler):
        self.handlers[event] = handler

    def reply(self, identity, session="owned", error=None):
        message = {"id": identity, "result": {"observed": True}}
        if error:
            message["error"] = error
        self.handlers["Target.receivedMessageFromTarget"]({"sessionId": session, "message": json.dumps(message)})

    async def send(self, method, params):
        self.calls.append((method, params))
        if method != "Target.sendMessageToTarget":
            return {}
        identity = json.loads(params["message"])["id"]
        if self.mode == "outer-error":
            raise RuntimeError("outer transport failure")
        if self.mode in ("close", "close-block"):
            self.handlers["close"]()
            if self.mode == "close-block":
                await asyncio.sleep(60)
            return {}
        if self.mode == "detach":
            self.handlers["Target.detachedFromTarget"]({"sessionId": "owned"})
            return {}
        self.reply(identity, "foreign")
        self.reply(identity + 100)
        if self.mode == "missing":
            return {}
        if self.mode == "after":
            asyncio.get_running_loop().call_soon(self.reply, identity)
        else:
            self.reply(identity, error="original protocol failure" if self.mode == "protocol-error" else None)
        if self.mode == "slow-ack":
            await asyncio.sleep(.1)
        return {}

    async def detach(self):
        self.detached = True


@pytest.mark.parametrize("mode", ("before", "after"))
def test_native_reply_order_preserves_arguments_and_has_no_timer_tail(mode):
    async def run():
        session = Session(mode)
        target = transport.NativeCDP(session, "owned", time.monotonic() + 1)
        result = await target.send("DOM.getDocument", {"depth": -1})
        assert result == {"observed": True} and target.pending == {}
        message = json.loads(session.calls[0][1]["message"])
        assert message == {"id": 1, "method": "DOM.getDocument", "params": {"depth": -1}}
        assert session.calls[0][1]["sessionId"] == "owned"
        await target.close()
        assert session.detached and target.closed
        with pytest.raises(RuntimeError, match="closed"):
            await target.send("DOM.getDocument")
    asyncio.run(run())


@pytest.mark.parametrize("mode,exception,match", (
    ("outer-error", RuntimeError, "outer transport failure"),
    ("protocol-error", RuntimeError, "original protocol failure"),
    ("missing", TimeoutError, "deadline"),
    ("slow-ack", TimeoutError, "deadline"),
    ("close", asyncio.CancelledError, None),
    ("close-block", asyncio.CancelledError, None),
    ("detach", asyncio.CancelledError, None),
))
def test_native_failure_cleans_pending_without_bypassing_whole_command_budget(mode, exception, match):
    async def run():
        session = Session(mode)
        target = transport.NativeCDP(session, "owned", time.monotonic() + .025)
        with pytest.raises(exception, match=match):
            await target.send("CSS.getComputedStyleForNode", {"nodeId": 7})
        assert not target.pending and not target.waiters
        session.reply(1)
        await target.close()
        assert session.detached
    asyncio.run(run())


def test_native_cancellation_and_expired_deadline_never_leave_pending_requests():
    async def run():
        session = Session("missing")
        target = transport.NativeCDP(session, "owned", time.monotonic() + 1)
        task = asyncio.create_task(target.send("DOM.getDocument"))
        await asyncio.sleep(0)
        assert target.pending
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not target.pending
        target.deadline = time.monotonic() - 1
        before = len(session.calls)
        with pytest.raises(TimeoutError, match="expired"):
            await target.send("DOM.getDocument")
        assert len(session.calls) == before
        await target.close()
    asyncio.run(run())


def test_stored_reply_cannot_succeed_after_synchronous_slow_outer_ack(monkeypatch):
    async def run():
        now = [0.0]
        monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])

        class SlowSession(Session):
            async def send(self, method, params):
                result = await super().send(method, params)
                now[0] = 10.0
                return result

        target = transport.NativeCDP(SlowSession("before"), "owned", 1.0)
        with pytest.raises(TimeoutError, match="deadline"):
            await target.send("DOM.getDocument")
        assert target.pending == {}
    asyncio.run(run())


@pytest.mark.parametrize("entrypoint", ("speed", "breakdown"))
def test_native_entrypoints_record_and_reraise_closure_failures(entrypoint, tmp_path, monkeypatch):
    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=object())))

        async def __aexit__(self, *_):
            return None

    harness = load_tool("check_speed_webview" if entrypoint == "speed" else "check_usage_breakdown_webview")
    output = tmp_path / "evidence"
    output.mkdir()
    monkeypatch.setattr(harness, "async_playwright", Playwright)
    monkeypatch.setattr(harness, "wait_cdp_endpoint", lambda *_: {"webSocketDebuggerUrl": "ws://synthetic", "Browser": "synthetic"})
    monkeypatch.setattr(harness, "attach_speed_target", AsyncMock(side_effect=asyncio.CancelledError("original closure")))
    stopped = []
    if entrypoint == "speed":
        with pytest.raises(asyncio.CancelledError, match="original closure"):
            asyncio.run(harness.accept_native_link_async(tmp_path, 1, time.monotonic() + 5, output))
    else:
        monkeypatch.setattr(harness, "prepare_extension", lambda *_: None)

        def process(*_, env, **__):
            Path(env["CODEX_SPEED_ACCEPTANCE_ROOT"]).joinpath("ready.json").write_text("{}")
            return SimpleNamespace(poll=lambda: None)

        monkeypatch.setattr(harness.subprocess, "Popen", process)
        monkeypatch.setattr(harness, "stop_owned_host", lambda process: stopped.append(process))
        monkeypatch.setattr(sys, "argv",
            ["native", "--code", str(tmp_path / "Code"), "--output", str(output)])
        with pytest.raises(asyncio.CancelledError, match="original closure"):
            asyncio.run(harness.main())
        assert len(stopped) == 1
    diagnostics = json.loads((output / "cdp-diagnostics.json").read_text())
    assert diagnostics["failure"] == "CancelledError: original closure"


def test_standalone_speed_provenance_includes_extracted_transport():
    harness = load_tool("check_speed_webview")
    hashes = harness.source_fingerprints(Path(__file__).resolve().parents[1])
    assert "scripts/native_cdp.py" in hashes
    assert len(hashes["scripts/native_cdp.py"]) == 64
