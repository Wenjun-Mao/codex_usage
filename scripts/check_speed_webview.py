"""Accept actual script-disabled VS Code command links in an isolated synthetic host."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
import time

from playwright.sync_api import sync_playwright

from observed_speed_fixture import chart_home


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
                    "codexUsage.range": "all",
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
        command = [
            str(args.code),
            "--new-window",
            "--disable-workspace-trust",
            "--skip-welcome",
            "--skip-release-notes",
            f"--user-data-dir={root / 'user-data'}",
            f"--extensions-dir={root / 'extensions'}",
            f"--extensionDevelopmentPath={extension}",
            f"--extensionTestsPath={extension / 'acceptance.js'}",
            f"--remote-debugging-port={port}",
            "--disable-updates",
        ]
        with (args.output / "host.log").open("w") as log:
            process = subprocess.Popen(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
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
                (args.output / "evidence.json").write_text(
                    json.dumps(evidence, indent=2) + "\n"
                )
                print(json.dumps(evidence))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)


def accept_native_link(root, port, deadline, output):
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{port}", timeout=15000
        )
        page = browser.contexts[0].pages[0]
        target = None
        while target is None and time.monotonic() < deadline:
            target = next(
                (
                    frame
                    for frame in page.frames
                    if frame.locator(".observed-speed").count()
                ),
                None,
            )
            if target is None:
                time.sleep(0.1)
        assert target is not None, "real webview frame not rendered"
        modes = target.get_by_role("navigation", name="Speed granularity")
        modes.get_by_role("link", name="Hourly", exact=True).click()
        target.locator(".speed-window").wait_for()
        target.locator(".observed-speed").screenshot(
            path=str(output / "native-hourly.png")
        )
        (root / "clicked.json").write_text("{}")
        browser.close()


if __name__ == "__main__":
    main()
