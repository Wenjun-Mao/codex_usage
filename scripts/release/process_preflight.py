"""Conservative local suite selection; these passes are never release proof."""
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import sys
from uuid import uuid4

from .policy import ROOT, VISUALS, fingerprint, require
from .process_candidate import changes, inputs
from .process_state import atomic_json, command
from run_visual_suite import SCRIPTS
from verification.visual_cases import validate_inventory


FAST_TESTS = ("tests/test_release_history.py", "tests/test_github_actions_workflow.py",
    "tests/test_breakdown_layout_snapshot.py", "tests/test_speed_tooltip_harness.py")
DOC_FILES = {"README.md", "CHANGELOG.md", "SUPPORT.md", "LICENSE", "LICENSE.txt",
    "extensions/vscode/README.md", "extensions/vscode/CHANGELOG.md", "extensions/vscode/SUPPORT.md"}


def selection(paths):
    reasons = {}
    for path in paths:
        if path.startswith("docs/") or path in DOC_FILES:
            reasons[path] = []
        elif path.startswith("src/codex_usage/report_speed") or path in {
            "scripts/check_speed_ui.py", "scripts/observed_speed_fixture.py",
            "scripts/verification/speed_tooltips.py"}:
            reasons[path] = ["screenshots-allowance", "speed"]
        elif path.startswith("src/codex_usage/report_economics") or path == "scripts/check_project_economics_ui.py":
            reasons[path] = ["screenshots-allowance"]
        else:
            # Unknown includes shared renderers, fixtures, tests, workflows and dependencies.
            reasons[path] = list(VISUALS)
    suites = [s for s in VISUALS if any(s in chosen for chosen in reasons.values())]
    return suites, reasons


def environment():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as browser:
        engines = {}
        for name in ("chromium", "webkit", "firefox"):
            engine = getattr(browser, name)
            # A real public launch/close round trip also completes driver initialization.
            instance = engine.launch()
            try:
                engines[name] = {"sha256": sha256(Path(engine.executable_path).read_bytes()).hexdigest(),
                    "version": instance.version}
            finally:
                instance.close()
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "machine": platform.machine(), "mac": platform.mac_ver()[0], "playwright": version("playwright"),
        "node": command(["node", "--version"], capture=True), "engines": engines,
        "locale": {k: os.environ.get(k, "") for k in ("TZ", "LANG", "LC_ALL")}}


def identity(base, *, root=ROOT, env=None):
    base_sha, paths = changes(base, root)
    suites, reasons = selection(paths)
    return {"schema": 1, "base": base_sha, "inputs": fingerprint(inputs(root)),
        "environment": environment() if env is None else env, "suites": suites, "reasons": reasons}


def validate_pass(data, expected):
    require(data.get("status") == "local-preflight-only" and data.get("identity") == expected,
        "Local preflight inputs/environment differ")
    require(set(data.get("evidence", {})) == set(expected["suites"]), "Missing local preflight suite")
    for suite, directory in data["evidence"].items():
        directory = Path(directory).resolve()
        require(directory.is_relative_to((ROOT / "output").resolve()), "Foreign local evidence path")
        for child, *_ in SCRIPTS[suite]:
            raw = directory / child / "verification.json"
            require(not raw.is_symlink() and raw.resolve().is_relative_to(directory), "Foreign local evidence file")
            validate_inventory(json.loads(raw.read_text()), child)
    require(data.get("fast_tests") == list(FAST_TESTS), "Missing fast harness checks")
    return data


def preflight(base, directory, *, reuse=None, run_command=command, environment_reader=environment):
    directory = Path(directory)
    expected = identity(base, env=environment_reader())
    receipt = directory / "preflight.json"
    prior = Path(reuse) if reuse else receipt
    require(not prior.is_symlink() and prior.resolve().is_relative_to((ROOT / "output").resolve()),
        "Local preflight receipt must stay under ignored output/")
    if prior.exists():
        try:
            data = validate_pass(json.loads(prior.read_text()), expected)
        except (ValueError, OSError, KeyError, TypeError):
            pass
        else:
            atomic_json(receipt, data)
            return {"reused": True, "suites": expected["suites"], "receipt": str(receipt)}
    print(json.dumps({"preflight_selection": expected["reasons"]}, sort_keys=True), flush=True)
    run_command([sys.executable, "-m", "pytest", "-q", *FAST_TESTS])
    work = directory / ("preflight-" + str(uuid4()))
    work.mkdir(parents=True)
    evidence = {}
    for suite in expected["suites"]:
        output = work / suite
        run_command([sys.executable, "scripts/run_visual_suite.py", suite, "--output", output])
        evidence[suite] = str(output.resolve())
    require(identity(base, env=environment_reader()) == expected, "Inputs changed during local preflight")
    data = {"status": "local-preflight-only", "identity": expected, "fast_tests": list(FAST_TESTS),
        "evidence": evidence}
    validate_pass(data, expected)
    atomic_json(receipt, data)
    return {"reused": False, "suites": expected["suites"], "receipt": str(receipt)}
