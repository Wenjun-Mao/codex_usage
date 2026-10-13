import json
import re
import tomllib
from pathlib import Path

import pytest

from codex_usage import __version__

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
PROMOTION = ROOT / ".github" / "workflows" / "promote-vsix.yml"
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
    assert "  push:" not in text and "VSCE_PAT" not in text and "vsce publish" not in text
    assert 'test "$GITHUB_REF" = refs/heads/main' in text
    promotion = PROMOTION.read_text()
    assert "qualification_run:" in promotion and "qualification_attempt:" in promotion
    assert "default: true" in promotion and "if: inputs.dry_run == false" in promotion
    assert "validate-publication" in promotion and '--ref "$GITHUB_REF"' in promotion
    assert promotion.count('--promotion-run "$GITHUB_RUN_ID" --promotion-attempt "$GITHUB_RUN_ATTEMPT"') == 2
    assert promotion.index("Revalidate original proofs") < promotion.index("VSCE_PAT:")


def test_release_workflow_has_no_native_app_jobs_or_toolchain() -> None:
    workflow = read_workflow() + PROMOTION.read_text()
    for forbidden in ("macos-native:", "windows-native:", "apps/desktop", "cargo ",
                      "tauri", "--bundles dmg", "--bundles nsis", "prepare-native-release"):
        assert forbidden not in workflow


def test_platform_vsix_packages_are_built_and_published_independently() -> None:
    text = read_workflow()
    package = extract_workflow_job(text, "package")
    visual = extract_workflow_job(text, "visual")
    hosted = extract_workflow_job(text, "hosted")
    native = extract_workflow_job(text, "native")
    publish = extract_workflow_job(PROMOTION.read_text(), "publish")
    assert "os: macos-26" in package and "os: windows-2025" in package
    assert "script: package:vsix:mac" in package and "script: package:vsix:win" in package
    assert "npm run test:qualification" in package and "extension-tests.xml" in package
    assert "verify-vsix-archive.py" in package
    assert "accept_disposable_handoff.js" in package
    assert "codex-usage-companion-$TARGET.vsix" in package
    assert "max-parallel: 2" in visual and "fail-fast: false" in visual
    assert "suite: [screenshots-allowance, speed, breakdown, overlay, hover]" in visual
    assert "if: always()" in visual and "**/failure.png" in visual
    assert "needs: [metadata, core, package, visual]" in hosted
    assert "scripts/qualification.py freeze" in hosted
    assert "needs: hosted" in native and "--vsix output/native-input/qualified.vsix" in native
    assert "download_native_host.py" in native
    assert "validate-publication" in publish and "publish_qualified_vsix.cjs" in publish
    assert "npm ci --ignore-scripts" in publish and "needs.validate.outputs.trusted_sha" in publish
    assert "package:vsix" not in publish and "npm test" not in publish
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
    assert "target: darwin-arm64" in workflow and "target: win32-x64" in workflow
    assert "codex-usage-companion-$TARGET.vsix" in workflow
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


def test_metadata_gates_expensive_jobs_without_replacing_full_coverage() -> None:
    workflow = read_workflow()
    metadata = extract_workflow_job(workflow, "metadata")
    assert "tests/test_release_history.py tests/test_github_actions_workflow.py" in metadata
    core = extract_workflow_job(workflow, "core")
    assert "fetch-depth: 0" in core
    assert "scripts/check_speed_parity.py" in core and "scripts/check_speed_work.py" in core
    assert "uv run pytest -q -p verification.pytest_inventory" in core
    assert "--qualification-scope core" in core and "--junitxml=" in core and "--qualification-inventory" in core
    for name in ("core", "package", "visual"):
        assert "needs: metadata" in extract_workflow_job(workflow, name)
    assert "QUALIFICATION_PROBE:" in workflow
    record = (ROOT / ".github/actions/record-gate/action.yml").read_text()
    assert "artifact-id" in record and "artifact-digest" in record
    assert "-a${{ github.run_attempt }}" in record and "overwrite: true" not in record
    assert "scripts/qualification.py marker" in record


def test_journal_write_permission_is_job_scoped_and_pilot_has_no_publisher_secret() -> None:
    promotion = PROMOTION.read_text()
    validate = extract_workflow_job(promotion, "validate")
    publish = extract_workflow_job(promotion, "publish")
    assert "contents: write" not in validate and "contents: write" in publish
    assert "persist-credentials: false" in publish
    intent = (ROOT / ".github/actions/record-publication-intent/action.yml").read_text()
    assert intent.count("GH_TOKEN: ${{ github.token }}") == 2 and "VSCE_PAT" not in intent
    pilot = (ROOT / ".github/workflows/journal-pilot.yml").read_text()
    assert "scripts/publication_journal.py pilot" in pilot and "contents: write" in pilot
    assert "persist-credentials: false" in pilot
    assert "VSCE_PAT" not in pilot and "publish_qualified_vsix" not in pilot


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_changelogs_describe_2_0_release(changelog: Path) -> None:
    text = changelog.read_text(encoding="utf-8")
    section = text.split("## 2.0.0 - 2026-09-04", 1)[1].split("\n## ", 1)[0]

    assert "native" in section.casefold()
    assert "persistent" in section.casefold()
    assert re.search(r"15[- ]minute", section.casefold())
    assert "standalone" in section.casefold()
