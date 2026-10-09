"""Accept actual script-disabled VS Code command links in an isolated synthetic host."""

import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.error import URLError
from urllib.parse import unquote
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright

from observed_speed_fixture import chart_home
from speed_native_target import attach_speed_target, wait_native_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--code",
        type=Path,
        default=Path("/Applications/Visual Studio Code.app/Contents/MacOS/Code"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("output/playwright/observed-speed/native")
    )
    parser.add_argument(
        "--host-only",
        action="store_true",
        help="Check real host commands without claiming a rendered link click",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="speed-native-", dir="/tmp" if os.name != "nt" else None
    ) as raw:
        root = Path(raw).resolve()
        home = root / "codex"
        (root / "home").mkdir()
        chart_home(home)
        extension = root / "extension"
        extension.mkdir()
        source = repo / "extensions" / "vscode"
        for name in ("out", "bin"):
            shutil.copytree(source / name, extension / name)
        manifest = json.loads((source / "package.json").read_text())
        manifest["activationEvents"] = []
        (extension / "package.json").write_text(json.dumps(manifest))
        shutil.copy2(
            repo / "scripts" / "vscode_speed_acceptance.js", extension / "acceptance.js"
        )
        user = root / "user-data" / "User"
        user.mkdir(parents=True)
        (user / "settings.json").write_text(
            json.dumps(
                {
                    "codexUsage.range": "30d",
                    "codexUsage.theme": "day",
                    "telemetry.telemetryLevel": "off",
                    "update.mode": "none",
                    "extensions.autoUpdate": False,
                    "workbench.startupEditor": "none",
                }
            )
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment = dict(
            os.environ,
            HOME=str(root / "home"),
            CODEX_HOME=str(home),
            CODEX_USAGE_DATA_DIR=str(root / "settings"),
            CODEX_SPEED_ACCEPTANCE_ROOT=str(root),
            CODEX_SPEED_HOST_ONLY=str(args.host_only).lower(),
        )
        command = disposable_command(args.code, root, extension, port)
        with (args.output / "host.log").open("w") as log:
            process = subprocess.Popen(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            try:
                deadline = time.monotonic() + 120
                while not (root / "ready.json").exists():
                    if (root / "failure.txt").exists():
                        raise RuntimeError((root / "failure.txt").read_text())
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"VS Code test host exited {process.returncode}; see host.log"
                        )
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            "VS Code test host did not create the real webview"
                        )
                    time.sleep(0.1)
                if not args.host_only:
                    accept_native_link(root, port, deadline, args.output)
                while not (root / "host-evidence.json").exists():
                    if (root / "failure.txt").exists():
                        raise RuntimeError((root / "failure.txt").read_text())
                    if time.monotonic() > deadline:
                        raise TimeoutError("Native host checks did not complete")
                    time.sleep(.1)
                evidence = json.loads((root / "host-evidence.json").read_text())
                evidence["credential_isolation"] = {
                    "backend": "in-memory", "flag": "--use-inmemory-secretstorage",
                    "root_cause": "A temporary HOME does not disable Electron native credential storage. "
                                  "The supported test-only flag bypasses the native encryption check.",
                }
                evidence["source_sha256"] = source_fingerprints(repo)
                evidence["bundled_collector_sha256"] = hashlib.sha256(
                    (extension / "bin" / "darwin-arm64" / "codex-usage-agent").read_bytes()
                ).hexdigest() if os.name != "nt" else None
                evidence["native_target_contract"] = (
                    "Explicit vscode-webview iframe CDP target; DOM-derived real mouse input. "
                    "No injected script, host-only substitute, or CSP change."
                )
                (args.output / "evidence.json").write_text(
                    json.dumps(evidence, indent=2) + "\n"
                )
                print(json.dumps(evidence))
            finally:
                stop_owned_host(process)


def disposable_command(code, root, extension, port):
    assert root.name.startswith("speed-native-") and extension.parent == root
    return [str(code), "--new-window", "--disable-workspace-trust",
            "--skip-welcome", "--skip-release-notes", "--use-inmemory-secretstorage",
            f"--user-data-dir={root / 'user-data'}", f"--extensions-dir={root / 'extensions'}",
            f"--extensionDevelopmentPath={extension}",
            f"--extensionTestsPath={extension / 'acceptance.js'}",
            f"--remote-debugging-port={port}", "--disable-updates"]


def source_fingerprints(repo):
    paths = ("scripts/check_speed_webview.py", "scripts/speed_native_target.py",
             "scripts/vscode_speed_acceptance.js", "extensions/vscode/src/speedNavigation.ts",
             "extensions/vscode/src/reportHtml.ts", "src/codex_usage/speed_parser.py",
             "src/codex_usage/speed_projection.py", "src/codex_usage/session_chunk_reader.py")
    return {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in paths}


def stop_owned_host(process):
    # POSIX hosts start in their own session; this group cannot contain regular Code.
    group_permission_error = None
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            group_permission_error = error
            if process.poll() is None:
                process.terminate()
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    finally:
        if os.name != "nt":
            # Reap the parent before testing group retirement: an unreaped
            # owned child is still listed by ps but cannot receive signals.
            if group_permission_error is not None:
                if not wait_owned_group_exit(process.pid):
                    raise group_permission_error
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    if not wait_owned_group_exit(process.pid):
                        raise


def owned_group_exists(group):
    # A completed VS Code host can retire its group while macOS rejects a stale
    # signal with EPERM rather than ESRCH. Never suppress a live-group failure.
    result = subprocess.run(["ps", "-axo", "pgid="], check=True, capture_output=True, text=True)
    return str(group) in result.stdout.split()


def wait_owned_group_exit(group):
    deadline = time.monotonic() + 5
    while owned_group_exists(group):
        if time.monotonic() >= deadline:
            return False
        time.sleep(.1)
    return True


def accept_native_link(root, port, deadline, output):
    diagnostics = {"synthetic_only": True, "stage": "endpoint", "endpoint_attempts": 0}
    diagnostics_path = output / "cdp-diagnostics.json"
    try:
        started = time.monotonic()
        endpoint = wait_cdp_endpoint(port, deadline, diagnostics)
        diagnostics.update(stage="browser_attach", endpoint_available=True,
                           endpoint_seconds=time.monotonic() - started, browser=endpoint["Browser"])
        diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
        with sync_playwright() as playwright:
            started = time.monotonic()
            browser = playwright.chromium.connect_over_cdp(
                endpoint["webSocketDebuggerUrl"], timeout=15000
            )
            diagnostics.update(stage="frame_target", browser_attached=True,
                               attach_seconds=time.monotonic() - started)
            diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
            target, state = attach_speed_target(browser, deadline, navigation_args, diagnostics, diagnostics_path)
            assert state["granularity"] == "daily", state
            diagnostics["initial_state"] = state
            clicks = []
            # Each command replaces webview.html and therefore its content frame.
            for label in ("Hourly", "Previous", "Previous", "Latest week", "Previous", "Next", "Daily", "Hourly"):
                args = target.click(label, navigation_args)
                state = wait_native_state(target, args, navigation_args, matches_navigation)
                clicks.append({"label": label, "requested": args, "rendered": state})
                target.screenshot(output / f"native-{len(clicks)}-{label.lower()}.png")
            diagnostics.update(stage="complete", rendered_clicks=clicks)
            (root / "clicked.json").write_text(json.dumps(clicks))
            target.close()
            browser.close()
    except Exception as error:
        diagnostics["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")


def wait_cdp_endpoint(port, deadline, diagnostics):
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        diagnostics["endpoint_attempts"] += 1
        try:
            with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
                endpoint = json.load(response)
            assert endpoint["webSocketDebuggerUrl"].startswith(f"ws://127.0.0.1:{port}/")
            return endpoint
        except (URLError, TimeoutError) as error:
            diagnostics["last_endpoint_error"] = type(error).__name__
            time.sleep(.1)
    raise TimeoutError("CDP endpoint did not respond before attachment")


def navigation_args(uri):
    assert uri and uri.startswith("command:codexUsage.navigateSpeed?")
    return json.loads(unquote(uri.split("?", 1)[1]))[0]


def matches_navigation(state, expected):
    return (state["granularity"] == expected["granularity"] and
            state["scope"] == expected["scope"] and
            state["window_start"] == expected["windowStart"] and
            (isinstance(state["window_label"], str) and
             state["window_label"].startswith(expected["windowStart"] + " to ")
             if expected["granularity"] == "hourly" else state["window_label"] is None))


if __name__ == "__main__":
    main()
