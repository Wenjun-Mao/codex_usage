"""Trusted qualification contract, independent of caller-supplied receipts."""
from hashlib import sha1, sha256
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "Wenjun-Mao/codex_usage"
WORKFLOW = ".github/workflows/package-vsix.yml"
PROMOTION_WORKFLOW = ".github/workflows/promote-vsix.yml"
TARGETS = ("darwin-arm64", "win32-x64")
VISUALS = ("screenshots-allowance", "speed", "breakdown", "overlay", "hover")
GATES = {"metadata": "Release metadata", "core": "Core and accounting",
    **{f"package-{target}": f"Package ({target})" for target in TARGETS},
    **{f"visual-{suite}": f"Visual ({suite})" for suite in VISUALS}}
JOBS = {**GATES, "hosted": "Freeze hosted qualification", "native": "Native macOS"}
SCHEMA = 1
PROMOTION_ENABLED = True
PROMOTION_BLOCKER = "Production promotion awaits full source-bound qualification of independently retained publication authority"
MAX_ARCHIVE = 250 * 1024 * 1024
HOST = {"version": "1.141.0", "commit": "2a59476c9bfcb90b3ddc372c36762471b7dfad1c",
    "sha256": "9b4ae386e3cf738d7ba990237ddf0a18092c924a1bcae465ed4697964745f42d",
    "url": "https://vscode.download.prss.microsoft.com/dbazure/download/stable/"
        "2a59476c9bfcb90b3ddc372c36762471b7dfad1c/VSCode-darwin-arm64.zip"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    require(type(value) is int or isinstance(value, str), "Invalid identifier type")
    text = str(value)
    require(re.fullmatch(r"[1-9][0-9]{0,19}", text) is not None, "Invalid positive identifier")
    return int(text)


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "Invalid SHA-256")
    return value


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def fingerprint(data):
    return sha256(canonical(data)).hexdigest()


def contract_files(root=ROOT):
    files = [WORKFLOW, PROMOTION_WORKFLOW, ".github/actions/record-gate/action.yml",
        ".github/workflows/journal-pilot.yml", "scripts/publication_journal.py", "scripts/release/journal-origins.json",
        ".github/actions/record-publication-intent/action.yml", "scripts/publication_intent.py",
        ".github/actions/qualification-tools/action.yml", "scripts/qualification.py",
        "scripts/run_visual_suite.py", "scripts/check_usage_breakdown_webview.py",
        "scripts/verify-vsix-archive.py", "scripts/verify_marketplace_release.cjs",
        "scripts/publish_qualified_vsix.cjs", "scripts/download_native_host.py",
        "extensions/vscode/scripts/cliEntrypoints.js",
        "extensions/vscode/scripts/test-qualification.js", "extensions/vscode/package.json",
        "extensions/vscode/scripts/qualification-reporter.cjs",
        "scripts/verification/python-case-baseline.json", "scripts/verification/extension-case-baseline.json",
        "scripts/check_speed_webview.py", "scripts/speed_native_target.py", "scripts/native_cdp.py",
        "scripts/breakdown_rpc_fixture.py", "scripts/usage_breakdown_fixture.py",
        "uv.lock", "extensions/vscode/package-lock.json"]
    files += ["src/codex_usage/" + name for name in
        ("process_tree.py", "windows_job.py", "windows_job_controller.py")]
    files += [file.relative_to(root).as_posix() for directory in ("scripts/release", "scripts/verification")
        for file in (root / directory).iterdir() if file.suffix in (".py", ".cjs")]
    files += ["scripts/" + file for file in ("check_usage_breakdown_ui.py", "check_speed_ui.py",
        "check_allowance_ui.py", "check_breakdown_overlay_ui.py", "check_breakdown_hover_ui.py",
        "generate_marketplace_screenshot.py", "breakdown_native_hover.py", "vscode_breakdown_acceptance.js")]
    files += ["scripts/check_project_economics_ui.py"]
    files += ["scripts/" + name for name in (
        "build-agent-macos-arm64.sh", "build-agent-windows-x64.ps1",
        "smoke-test-packaged-agent.py", "packaged_agent_parallel_smoke.py",
        "packaged_parallel_cache_smoke.py", "observed_speed_fixture.py", "collector_smoke_owner.py",
        "packaged_windows_process_tree_smoke.py", "parallel_cache_fixture.py")]
    files += ["src/codex_usage/parallel_audit.py"]
    return sorted(set(files))


def contract_identity(root=ROOT):
    # Checkout line-ending conversion is not a different workflow contract.
    return fingerprint({file: sha256((root / file).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for file in contract_files(root)})


def contract_blobs(root=ROOT):
    blobs = {}
    for name in contract_files(root):
        data = (root / name).read_bytes().replace(b"\r\n", b"\n")
        blobs[name] = sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    return blobs


def package_version(root=ROOT):
    return json.loads((root / "extensions/vscode/package.json").read_text())["version"]
