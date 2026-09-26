import json
import re
import tomllib
from pathlib import Path

import pytest

from codex_usage import __version__

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
EXTENSION_ROOT = ROOT / "extensions" / "vscode"
EXTENSION_PACKAGE = EXTENSION_ROOT / "package.json"
EXTENSION_PACKAGE_LOCK = EXTENSION_ROOT / "package-lock.json"
CHANGELOGS = (ROOT / "CHANGELOG.md", EXTENSION_ROOT / "CHANGELOG.md")


def read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def extract_workflow_job(text: str, job_name: str) -> str:
    jobs = text.split("\njobs:\n", 1)[1]
    headers = list(
        re.finditer(r"^  (?P<name>[A-Za-z0-9_-]+):\n", jobs, re.MULTILINE)
    )
    for index, header in enumerate(headers):
        if header.group("name") != job_name:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(jobs)
        return jobs[header.end() : end]
    raise AssertionError(f"Workflow job not found: {job_name}")


def test_workflow_requires_a_matching_tag_for_marketplace_publication() -> None:
    text = read_workflow()

    assert "workflow_dispatch:" in text
    assert "publish:" in text and "default: false" in text
    assert '"v*"' in text
    assert "Marketplace publication requires dispatching a matching" in text
    assert 'expected_tag="v${version}"' in text
    assert "git merge-base --is-ancestor" in text


def test_release_workflow_has_no_native_app_jobs_or_toolchain() -> None:
    workflow = read_workflow()
    for forbidden in ("macos-native:", "windows-native:", "apps/desktop", "cargo ",
                      "tauri", "--bundles dmg", "--bundles nsis", "prepare-native-release"):
        assert forbidden not in workflow


def test_platform_vsix_packages_are_built_and_published_independently() -> None:
    text = read_workflow()
    macos = extract_workflow_job(text, "macos-vsix")
    windows = extract_workflow_job(text, "windows-vsix")
    publish = extract_workflow_job(text, "publish-vsix")

    assert "runs-on: macos-26" in macos
    assert "npm run package:vsix:mac" in macos
    assert "codex-usage-companion-darwin-arm64.vsix" in macos
    assert "verify-vsix-archive.py" in macos
    assert "generate_marketplace_screenshot.py --check" in macos
    assert "check_allowance_ui.py" in macos
    assert "runs-on: windows-2025" in windows
    assert "npm run package:vsix:win" in windows
    assert "codex-usage-companion-win32-x64.vsix" in windows
    assert "verify-vsix-archive.py" in windows

    assert "macos-vsix" in publish and "windows-vsix" in publish
    assert "macos-native" not in publish and "windows-native" not in publish
    assert "actions/download-artifact@v6" in publish
    assert "npx vsce publish --skip-duplicate" in publish
    assert "codex-usage-companion-darwin-arm64.vsix" in publish
    assert "codex-usage-companion-win32-x64.vsix" in publish
    assert "gh release" not in publish


def test_release_metadata_is_consistently_versioned() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    extension = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    extension_lock = json.loads(EXTENSION_PACKAGE_LOCK.read_text(encoding="utf-8"))

    codex_usage_lock = next(
        package for package in uv_lock["package"] if package["name"] == "codex-usage"
    )
    versions = {
        pyproject["project"]["version"],
        __version__,
        codex_usage_lock["version"],
        extension["version"],
        extension_lock["version"],
        extension_lock["packages"][""]["version"],
    }
    assert versions == {extension["version"]}
    assert "scripts" not in pyproject["project"]
    assert "preview" not in extension


def test_companion_package_contract_requires_platform_specific_collectors() -> None:
    extension = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    workflow = read_workflow()
    command_titles = {
        command["command"]: command["title"]
        for command in extension["contributes"]["commands"]
    }

    assert extension["displayName"] == "Codex Usage Companion"
    assert command_titles["codexUsage.captureNow"] == "Codex Usage: Capture Usage"
    assert command_titles["codexUsage.refreshDashboard"] == (
        "Codex Usage: Reload Current View"
    )
    assert "package:vsix:win" in json.dumps(extension)
    assert "package:vsix:mac" in json.dumps(extension)
    assert "codex-usage-companion-darwin-arm64.vsix" in workflow
    assert "codex-usage-companion-win32-x64.vsix" in workflow
    assert "codex-usage-companion.vsix" not in workflow
    assert "codex-usage-dashboard-win32" not in workflow
    assert "codex-usage-dashboard-darwin" not in workflow


def test_release_targets_only_supported_native_platforms() -> None:
    workflow = read_workflow()

    assert "darwin-arm64" in workflow
    assert "win32-x64" in workflow
    assert "linux-x64" not in workflow
    assert "x86_64-apple-darwin" not in workflow
    assert "aarch64-pc-windows" not in workflow


def test_release_visual_gate_installs_all_meter_styling_engines() -> None:
    workflow = read_workflow()

    assert "uv run playwright install chromium firefox webkit" in workflow


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_changelogs_describe_2_0_release(changelog: Path) -> None:
    text = changelog.read_text(encoding="utf-8")
    section = text.split("## 2.0.0 - 2026-09-04", 1)[1].split("\n## ", 1)[0]

    assert "native" in section.casefold()
    assert "persistent" in section.casefold()
    assert re.search(r"15[- ]minute", section.casefold())
    assert "standalone" in section.casefold()
