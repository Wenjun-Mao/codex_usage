import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from codex_usage import __version__

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
DESKTOP_ROOT = ROOT / "apps" / "desktop"
DESKTOP_PACKAGE = DESKTOP_ROOT / "package.json"
DESKTOP_PACKAGE_LOCK = DESKTOP_ROOT / "package-lock.json"
TAURI_CONFIG = DESKTOP_ROOT / "src-tauri" / "tauri.conf.json"
TAURI_WINDOWS_CONFIG = DESKTOP_ROOT / "src-tauri" / "tauri.windows.conf.json"
CARGO_TOML = DESKTOP_ROOT / "src-tauri" / "Cargo.toml"
CARGO_LOCK = DESKTOP_ROOT / "src-tauri" / "Cargo.lock"
EXTENSION_ROOT = ROOT / "extensions" / "vscode"
EXTENSION_PACKAGE = EXTENSION_ROOT / "package.json"
EXTENSION_PACKAGE_LOCK = EXTENSION_ROOT / "package-lock.json"
CHANGELOGS = (ROOT / "CHANGELOG.md", EXTENSION_ROOT / "CHANGELOG.md")
PREVIEW_ARTIFACTS = {
    "darwin-aarch64": "Codex-Usage-{version}-macos-arm64-unsigned-preview.dmg",
    "windows-x86_64": "Codex-Usage-{version}-windows-x64-unsigned-preview-setup.exe",
}


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


@pytest.mark.parametrize(
    ("job_name", "runner", "bundle"),
    (
        ("macos-native", "macos-26", "--bundles dmg --ci"),
        ("windows-native", "windows-2025", "--bundles nsis --ci"),
    ),
)
def test_native_jobs_build_unsigned_platform_previews(
    job_name: str, runner: str, bundle: str
) -> None:
    job = extract_workflow_job(read_workflow(), job_name)

    assert f"runs-on: {runner}" in job
    assert "Build and smoke-test packaged agent" in job
    assert "npm test" in job and "cargo test" in job and "cargo clippy" in job
    assert "Build unsigned native preview" in job
    assert bundle in job
    assert "prepare-native-release.py" in job
    assert "Upload" in job and "preview" in job


def test_native_preview_contract_has_no_paid_signing_dependency() -> None:
    workflow = read_workflow()
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    windows_config = json.loads(TAURI_WINDOWS_CONFIG.read_text(encoding="utf-8"))

    assert config["bundle"]["createUpdaterArtifacts"] is False
    assert windows_config["bundle"]["createUpdaterArtifacts"] is False
    for forbidden in (
        "secrets.APPLE_",
        "secrets.AZURE_",
        "secrets.ARTIFACT_SIGNING_",
        "secrets.TAURI_SIGNING_",
        "azure/login",
        "artifact-signing",
        "codesign",
        "notar",
        "verify_updater_signature",
    ):
        assert forbidden not in workflow


def test_platform_vsix_packages_are_built_and_published_independently() -> None:
    text = read_workflow()
    macos = extract_workflow_job(text, "macos-vsix")
    windows = extract_workflow_job(text, "windows-vsix")
    publish = extract_workflow_job(text, "publish-vsix")

    assert "runs-on: macos-26" in macos
    assert "npm run package:vsix:mac" in macos
    assert "codex-usage-companion-darwin-arm64.vsix" in macos
    assert "runs-on: windows-2025" in windows
    assert "npm run package:vsix:win" in windows
    assert "codex-usage-companion-win32-x64.vsix" in windows

    assert "macos-vsix" in publish and "windows-vsix" in publish
    assert "macos-native" not in publish and "windows-native" not in publish
    assert "actions/download-artifact@v6" in publish
    assert "npx vsce publish --skip-duplicate" in publish
    assert "codex-usage-companion-darwin-arm64.vsix" in publish
    assert "codex-usage-companion-win32-x64.vsix" in publish
    assert "gh release" not in publish


def test_preview_artifacts_include_hash_based_integrity_metadata(tmp_path: Path) -> None:
    version = "2.1.1"
    for platform, pattern in PREVIEW_ARTIFACTS.items():
        artifact_name = pattern.format(version=version)
        artifact = tmp_path / artifact_name
        artifact.write_bytes(f"preview-{platform}".encode())

        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "prepare-native-release.py"),
                "--directory",
                str(tmp_path),
                "--version",
                version,
                "--platform",
                platform,
            ],
            check=True,
        )

        integrity = json.loads(
            (tmp_path / "preview-integrity.json").read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert integrity["schema_version"] == 1
        assert integrity["kind"] == "codex-usage-unsigned-preview-integrity"
        assert integrity["version"] == version
        assert integrity["platform"] == platform
        assert integrity["artifact"] == {"name": artifact_name, "sha256": digest}
        assert integrity["generated_at"].endswith("Z")
        assert (tmp_path / "SHA256SUMS.txt").read_text(encoding="ascii") == (
            f"{digest}  {artifact_name}\n"
        )


def test_release_metadata_is_consistently_2_2_0() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    extension = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    extension_lock = json.loads(EXTENSION_PACKAGE_LOCK.read_text(encoding="utf-8"))
    desktop = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
    desktop_lock = json.loads(DESKTOP_PACKAGE_LOCK.read_text(encoding="utf-8"))
    tauri = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    cargo = tomllib.loads(CARGO_TOML.read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))

    codex_usage_lock = next(
        package for package in uv_lock["package"] if package["name"] == "codex-usage"
    )
    rust_package = next(
        package
        for package in cargo_lock["package"]
        if package["name"] == "codex-usage-desktop"
    )
    versions = {
        pyproject["project"]["version"],
        __version__,
        codex_usage_lock["version"],
        extension["version"],
        extension_lock["version"],
        extension_lock["packages"][""]["version"],
        desktop["version"],
        desktop_lock["version"],
        desktop_lock["packages"][""]["version"],
        tauri["version"],
        cargo["package"]["version"],
        rust_package["version"],
    }
    assert versions == {"2.2.0"}
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

    assert "aarch64-apple-darwin" in workflow
    assert "x86_64-pc-windows-msvc" in workflow
    assert "linux-x64" not in workflow
    assert "x86_64-apple-darwin" not in workflow
    assert "aarch64-pc-windows" not in workflow


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_changelogs_describe_2_0_release(changelog: Path) -> None:
    text = changelog.read_text(encoding="utf-8")
    section = text.split("## 2.0.0 - 2026-09-04", 1)[1].split("\n## ", 1)[0]

    assert "native" in section.casefold()
    assert "persistent" in section.casefold()
    assert re.search(r"15[- ]minute", section.casefold())
    assert "standalone" in section.casefold()
