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
CARGO_TOML = DESKTOP_ROOT / "src-tauri" / "Cargo.toml"
CARGO_LOCK = DESKTOP_ROOT / "src-tauri" / "Cargo.lock"
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


def test_workflow_has_nonpublishing_dispatch_and_tag_release() -> None:
    text = read_workflow()

    assert "workflow_dispatch:" in text
    assert "publish:" in text and "default: false" in text
    assert '"v*"' in text
    assert "Signed publication requires dispatching a matching" in text
    assert 'expected_tag="v${version}"' in text
    assert "git merge-base --is-ancestor" in text


@pytest.mark.parametrize(
    ("job_name", "runner"),
    (("macos-native", "macos-26"), ("windows-native", "windows-2025")),
)
def test_native_jobs_run_platform_gates(job_name: str, runner: str) -> None:
    job = extract_workflow_job(read_workflow(), job_name)

    assert f"runs-on: {runner}" in job
    assert "Build and smoke-test packaged agent" in job
    assert "npm test" in job and "cargo test" in job and "cargo clippy" in job
    assert "--no-bundle --ci" in job


def test_release_is_signed_only_on_both_platforms() -> None:
    text = read_workflow()
    macos = extract_workflow_job(text, "macos-native")
    windows = extract_workflow_job(text, "windows-native")

    for secret in (
        "APPLE_CERTIFICATE",
        "APPLE_SIGNING_IDENTITY",
        "APPLE_ID",
        "APPLE_PASSWORD",
        "APPLE_TEAM_ID",
    ):
        assert f"secrets.{secret}" in macos
    assert "codesign --verify --deep --strict" in macos
    assert "spctl --assess --type execute" in macos
    assert "xcrun stapler validate" in macos
    assert "--skip-stapling" not in macos

    assert "permissions:\n      contents: read\n      id-token: write" in windows
    assert "azure/login@v2" in windows
    assert windows.count("azure/artifact-signing-action@v2") == 2
    assert "Get-AuthenticodeSignature" in windows
    assert "--no-sign" not in windows


def test_windows_signing_order_preserves_updater_integrity() -> None:
    windows = extract_workflow_job(read_workflow(), "windows-native")

    sign_binary = windows.index("Sign Windows application and agent")
    bundle = windows.index("Bundle NSIS installer")
    sign_installer = windows.index("Sign NSIS installer")
    repack = windows.index("Build and sign Windows updater archive")
    verify = windows.index("Verify Windows signatures")
    assert sign_binary < bundle < sign_installer < repack < verify
    assert "repack-signed-windows-updater.ps1" in windows
    assert "tauri signer sign" in windows


def test_updater_has_committed_public_key_and_secret_backed_signing() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    workflow = read_workflow()
    cargo = tomllib.loads(CARGO_TOML.read_text(encoding="utf-8"))

    pubkey = config["plugins"]["updater"]["pubkey"]
    assert isinstance(pubkey, str) and len(pubkey) > 80
    assert config["bundle"]["createUpdaterArtifacts"] is True
    assert workflow.count("secrets.TAURI_SIGNING_PRIVATE_KEY") >= 2
    assert workflow.count("secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD") >= 2
    assert workflow.count("--example verify_updater_signature") == 2
    assert cargo["dev-dependencies"]["minisign-verify"] == "0.2.5"
    assert "latest.json" in workflow


def test_windows_uninstall_preserves_data_by_default() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    hook_path = DESKTOP_ROOT / "src-tauri" / config["bundle"]["windows"]["nsis"]["installerHooks"]
    hook = hook_path.read_text(encoding="utf-8")

    assert "NSIS_HOOK_PREUNINSTALL" in hook
    assert "--uninstall-service" in hook
    assert "MB_DEFBUTTON2" in hook
    assert "IDNO preserve_local_data" in hook
    assert "--reset-local-data --remove-settings" in hook


def test_release_artifacts_are_uploaded_before_publication() -> None:
    text = read_workflow()
    publish = extract_workflow_job(text, "publish")

    assert "actions/upload-artifact@v6" in text
    assert "actions/download-artifact@v6" in publish
    assert "if-no-files-found: error" in text
    assert "retention-days: 14" in text
    assert "gh release create" in publish and "gh release upload" in publish
    assert "--clobber" in publish
    assert "npx vsce publish --skip-duplicate" in publish
    assert "SHA256SUMS.txt" in publish


def test_release_metadata_is_consistently_2_0_0() -> None:
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
    assert versions == {"2.0.0"}
    assert "scripts" not in pyproject["project"]
    assert "preview" not in extension


def test_companion_package_contains_no_parser_or_native_runtime() -> None:
    extension = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    workflow = read_workflow()

    assert extension["displayName"] == "Codex Usage Companion"
    assert "package:vsix:win" not in json.dumps(extension)
    assert "package:vsix:mac" not in json.dumps(extension)
    assert "codex-usage-companion.vsix" in workflow
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
    section = text.split("## 2.0.0 - 2026-09-03", 1)[1].split("\n## ", 1)[0]

    assert "native" in section.casefold()
    assert "persistent" in section.casefold()
    assert re.search(r"15[- ]minute", section.casefold())
    assert "companion" in section.casefold()


def test_prepare_native_release_builds_platform_manifest(tmp_path: Path) -> None:
    version = "2.0.0"
    names = (
        f"Codex-Usage-{version}-darwin-aarch64.app.tar.gz",
        f"Codex-Usage-{version}-windows-x86_64.nsis.zip",
    )
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
        (tmp_path / f"{name}.sig").write_text(f"signature-{name}\n", encoding="utf-8")
    for name in (
        f"Codex-Usage-{version}-macos-arm64.dmg",
        f"Codex-Usage-{version}-windows-x64-setup.exe",
        "codex-usage-companion.vsix",
    ):
        (tmp_path / name).write_bytes(name.encode())

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare-native-release.py"),
            "--directory",
            str(tmp_path),
            "--repository",
            "Wenjun-Mao/codex_usage",
            "--version",
            version,
            "--published-at",
            "2026-09-02T00:00:00Z",
        ],
        check=True,
    )

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["version"] == version
    assert set(latest["platforms"]) == {"darwin-aarch64", "windows-x86_64"}
    assert latest["platforms"]["windows-x86_64"]["url"].endswith(names[1])
    checksums = (tmp_path / "SHA256SUMS.txt").read_text(encoding="ascii")
    assert "latest.json" in checksums
    assert "codex-usage-companion.vsix" in checksums


def test_release_document_uses_current_signed_release_contract() -> None:
    release_document = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")

    assert "`v2.0.0`" in release_document
    assert "Developer ID" in release_document
    assert "Artifact Signing" in release_document
    assert "no unsigned" in release_document.casefold()
