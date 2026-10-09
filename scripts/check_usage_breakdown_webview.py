"""Isolated script-free VS Code OOPIF DOM and real mouse/keyboard acceptance."""
import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.parse import unquote

from playwright.sync_api import sync_playwright
from codex_usage.agent_settings import AgentSettings, save_agent_settings

from check_speed_webview import disposable_command, stop_owned_host, wait_cdp_endpoint
from speed_native_target import NativeSpeedTarget, attach_speed_target, attributes, node_text, nodes, wait_native_state
from usage_breakdown_fixture import breakdown_home


def decode(uri):
    assert uri.startswith("command:codexUsage.navigateBreakdown?")
    return json.loads(unquote(uri.split("?", 1)[1]))[0]


class BreakdownTarget(NativeSpeedTarget):
    chart_class = "usage-breakdown"

    def state(self, _decode):
        chart = self.chart()
        if chart is None:
            return None
        return {"scope": attributes(chart)["data-scope"], "state": json.loads(attributes(chart)["data-state"])}

    def label_for(self, predicate):
        for node in nodes(self.chart()):
            if node.get("nodeName") == "A":
                uri = attributes(node).get("href", "")
                if uri.startswith("command:codexUsage.navigateBreakdown?") and predicate(decode(uri)["state"]):
                    return node_text(node)
        raise AssertionError("Expected rendered command absent")

    def screenshot(self, path):
        document = self.document()
        chart = next(n for n in nodes(document) if self.chart_class in attributes(n).get("class", "").split())
        toolbar = next(n for n in nodes(document) if "companion-actions" in attributes(n).get("class", "").split())
        self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": chart["nodeId"]})
        top = min(self.send("DOM.getContentQuads", {"nodeId": chart["nodeId"]})["quads"][0][1::2])
        bottom = max(self.send("DOM.getContentQuads", {"nodeId": toolbar["nodeId"]})["quads"][0][1::2])
        if top < bottom + 12:
            self.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 400, "y": bottom + 20,
                "deltaX": 0, "deltaY": top - bottom - 12})
            self.page.wait_for_timeout(100)
        self.page.screenshot(path=str(path), timeout=5000)

    def disclose(self, label):
        summary = next(n for n in nodes(self.chart()) if n.get("nodeName") == "SUMMARY" and node_text(n) == label)
        self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": summary["nodeId"]})
        quad = self.send("DOM.getContentQuads", {"nodeId": summary["nodeId"]})["quads"][0]
        x, y = sum(quad[::2])/4, sum(quad[1::2])/4
        hit = self.send("DOM.getNodeForLocation", {"x": round(x), "y": round(y)})
        assert hit["backendNodeId"] in {n.get("backendNodeId") for n in nodes(summary)}
        for event in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1})
        self.page.wait_for_timeout(100)

    def keyboard(self, label):
        # CDP DOM focus sets the input origin in the script-disabled OOPIF;
        # real Enter input and a changed rendered state prove activation.
        link = next(n for n in nodes(self.chart()) if n.get("nodeName") == "A" and node_text(n) == label)
        args = decode(attributes(link)["href"])
        self.send("DOM.scrollIntoViewIfNeeded", {"nodeId": link["nodeId"]})
        self.send("DOM.focus", {"nodeId": link["nodeId"]})
        before = self.state(decode)
        for event in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", {"type": event, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
        stop = time.monotonic() + 5
        while time.monotonic() < stop:
            state = self.state(decode)
            if state and state["state"] != before["state"]:
                assert state["state"] == args["state"]
                return {"keyboard": True, "requested": args, "before": before, "rendered": state, "focus_origin": "CDP DOM.focus; real Enter"}
            self.page.wait_for_timeout(100)
        raise AssertionError("Native Enter did not change the rendered mode")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", type=Path, default=Path("/Applications/Visual Studio Code.app/Contents/MacOS/Code"))
    parser.add_argument("--output", type=Path, default=Path("output/playwright/usage-breakdown/native"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    diagnostics = {"synthetic_only": True, "stage": "start", "endpoint_attempts": 0}
    diagnostics_path = args.output / "cdp-diagnostics.json"
    with TemporaryDirectory(prefix="speed-native-", dir="/tmp") as raw:
        root = Path(raw).resolve()
        home = root / "codex"
        (root / "home").mkdir()
        now = datetime.now(UTC).replace(microsecond=0)
        breakdown_home(home, now=now, extended=True, days=12)
        save_agent_settings(AgentSettings(str(home), capture_interval_minutes=None,
            onboarding_complete=True, timezone="UTC"), root / "settings" / "settings.json")
        rpc = root / "synthetic-codex"
        shutil.copy2(repo / "scripts/breakdown_rpc_fixture.py", rpc)
        rpc.chmod(0o700)
        rpc_fixture = root / "rpc.json"
        rpc_fixture.write_text(json.dumps({
            "account/read": {"account": {"planType": "pro"}},
            "account/rateLimits/read": {"rateLimitsByLimitId": {"codex": {
                "limitId": "codex", "planType": "pro", "secondary": {"usedPercent": 34,
                "windowDurationMins": 10080, "resetsAt": int((now + timedelta(days=4)).timestamp())},
                "credits": {"balance": "58.000000000000000001", "hasCredits": True, "unlimited": False}}}},
            "account/usage/read": {"summary": {"lifetimeTokens": 0}}}))
        extension = root / "extension"
        extension.mkdir()
        source = repo / "extensions" / "vscode"
        shutil.copytree(source / "out", extension / "out")
        binary = extension / "bin" / "darwin-arm64" / "codex-usage-agent"
        binary.parent.mkdir(parents=True)
        shutil.copy2(repo / "build/packaged-agent/aarch64-apple-darwin/codex-usage-agent-aarch64-apple-darwin", binary)
        manifest = json.loads((source / "package.json").read_text())
        manifest["activationEvents"] = []
        (extension / "package.json").write_text(json.dumps(manifest))
        shutil.copy2(repo / "scripts/vscode_breakdown_acceptance.js", extension / "acceptance.js")
        user = root / "user-data" / "User"
        user.mkdir(parents=True)
        (user / "settings.json").write_text(json.dumps({"codexUsage.range": "all", "codexUsage.theme": "day",
            "telemetry.telemetryLevel": "off", "update.mode": "none", "extensions.autoUpdate": False,
            "workbench.startupEditor": "none", "window.restoreWindows": "none"}))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment = dict(os.environ, HOME=str(root / "home"), CODEX_HOME=str(home),
                           CODEX_USAGE_DATA_DIR=str(root / "settings"), CODEX_SPEED_ACCEPTANCE_ROOT=str(root),
                           CODEX_CLI_PATH=str(rpc), CODEX_BREAKDOWN_RPC_FIXTURE=str(rpc_fixture))
        with (args.output / "host.log").open("w") as log:
            process = subprocess.Popen(disposable_command(args.code, root, extension, port),
                env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 120
                while not (root / "ready.json").exists():
                    if (root / "failure.txt").exists():
                        raise RuntimeError((root / "failure.txt").read_text())
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise TimeoutError("Disposable VS Code host not ready; see host.log")
                    time.sleep(.1)
                with sync_playwright() as playwright:
                    endpoint = wait_cdp_endpoint(port, deadline, diagnostics)
                    browser = playwright.chromium.connect_over_cdp(endpoint["webSocketDebuggerUrl"], timeout=15000)
                    target, state = attach_speed_target(browser, deadline, decode, diagnostics, diagnostics_path, BreakdownTarget)
                    (args.output / "initial-state.json").write_text(json.dumps(state, indent=2))
                    assert state["state"]["basis"] == "cycle", state
                    clicks = []
                    labels = ["Tokens", "By project", "Estimated credits", "API cost", "Project", "Estimated credits", "Tokens", "Other", "Hour", "Previous", "Next", "Latest day", "Selected range"]
                    for label in labels:
                        diagnostics["stage"] = "rendered click: " + label
                        diagnostics["before"] = target.state(decode)
                        diagnostics_path.write_text(json.dumps(diagnostics, indent=2))
                        if label == "Latest day":
                            for _ in range(2):
                                previous = target.click("Previous", decode)
                                wait_native_state(target, previous, decode, lambda s, a: s["state"] == a["state"])
                        if label == "Selected range":
                            target.disclose("Current observed window")
                        requested = target.click(label, decode)
                        target.deadline = min(deadline, time.monotonic() + 15)
                        state = wait_native_state(target, requested, decode, lambda s, a: s["state"] == a["state"])
                        target.deadline = deadline
                        clicks.append({"label": label, "requested": requested, "rendered": state})
                        diagnostics["rendered_clicks"] = clicks
                        diagnostics_path.write_text(json.dumps(diagnostics, indent=2))
                        target.screenshot(args.output / f"native-{len(clicks)}.png")
                    target.disclose("Selected range")
                    label = target.label_for(lambda s: s["basis"].startswith("window:") and s["day"] < (now-timedelta(days=7)).date().isoformat())
                    requested = target.click(label, decode)
                    state = wait_native_state(target, requested, decode, lambda s, a: s["state"] == a["state"])
                    clicks.append({"label": label, "requested": requested, "rendered": state})
                    target.screenshot(args.output / f"native-{len(clicks)}.png")
                    for prefix in ("project:", "hour:"):
                        if prefix == "project:":
                            requested = target.click("Project", decode)
                            wait_native_state(target, requested, decode, lambda s, a: s["state"] == a["state"])
                        else:
                            target.disclose("Inspect every hour occurrence")
                        label = target.label_for(lambda s: s["detail"].startswith(prefix))
                        requested = target.click(label, decode)
                        state = wait_native_state(target, requested, decode, lambda s, a: s["state"] == a["state"])
                        clicks.append({"label": label, "requested": requested, "rendered": state})
                        target.screenshot(args.output / f"native-{len(clicks)}.png")
                    clicks.append(target.keyboard("Project"))
                    (root / "clicked.json").write_text(json.dumps(clicks))
                    target.close()
                    browser.close()
                while not (root / "host-evidence.json").exists():
                    if (root / "failure.txt").exists():
                        raise RuntimeError((root / "failure.txt").read_text())
                    if time.monotonic() > deadline:
                        raise TimeoutError("Host acceptance did not complete")
                    time.sleep(.1)
                evidence = json.loads((root / "host-evidence.json").read_text())
                evidence["credential_isolation"] = "--use-inmemory-secretstorage; disposable HOME/CODEX_HOME/profile"
                evidence["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
                evidence["native_target_contract"] = "Explicit OOPIF CDP DOM, hit-tested real input; no injected scripts"
                (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
                diagnostics["stage"] = "complete"
                print(json.dumps({"native_inputs": len(evidence["rendered_input"]), "script_disabled": evidence["script_disabled"]}))
            except Exception as error:
                diagnostics["failure"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
                stop_owned_host(process)


if __name__ == "__main__":
    main()
