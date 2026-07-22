import json
import re
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
EXTENSION_ROOT = ROOT / "extensions" / "vscode"
EXTENSION_PACKAGE = EXTENSION_ROOT / "package.json"
EXTENSION_PACKAGE_LOCK = EXTENSION_ROOT / "package-lock.json"
CHANGELOGS = (ROOT / "CHANGELOG.md", EXTENSION_ROOT / "CHANGELOG.md")
NATIVE_BUILD_SCRIPTS = (
    ROOT / "scripts" / "build-macos-arm64-exe.sh",
    ROOT / "scripts" / "build-windows-exe.ps1",
)


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


def markdown_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(f"{heading}\n")
    level = heading.split(maxsplit=1)[0]
    remaining = text[start + len(heading) + 1 :]
    end_match = re.search(rf"^{re.escape(level)} (?!#)", remaining, re.MULTILINE)
    end = len(text) if end_match is None else start + len(heading) + 1 + end_match.start()
    return text[start:end]


def test_workflow_has_manual_and_tag_triggers():
    text = read_workflow()

    assert "workflow_dispatch:" in text
    assert "publish:" in text
    assert "type: boolean" in text
    assert "default: false" in text
    assert "push:" in text
    assert '"v*"' in text


def test_workflow_names_platform_vsix_files():
    text = read_workflow()

    assert "codex-usage-dashboard-win32-x64.vsix" in text
    assert "codex-usage-dashboard-darwin-arm64.vsix" in text


@pytest.mark.parametrize(
    ("job_name", "runner", "package_command"),
    (
        ("windows", "windows-2025", "npm run package:vsix:win"),
        ("macos", "macos-26", "npm run package:vsix:mac"),
    ),
)
def test_native_workflow_jobs_test_before_packaging(
    job_name: str,
    runner: str,
    package_command: str,
):
    job = extract_workflow_job(read_workflow(), job_name)

    assert f"runs-on: {runner}" in job
    assert f"run: {package_command}" in job
    assert job.index("run: uv run pytest -q") < job.index("run: npm test")
    assert job.index("run: npm test") < job.index(f"run: {package_command}")


@pytest.mark.parametrize("build_script", NATIVE_BUILD_SCRIPTS, ids=lambda path: path.name)
def test_native_build_scripts_run_packaged_sync_smoke(build_script: Path):
    text = build_script.read_text(encoding="utf-8")

    assert "smoke-test-packaged-sync.py" in text


def test_release_workflow_keeps_only_supported_platform_targets() -> None:
    workflow = read_workflow()

    assert "win32-x64" in workflow
    assert "darwin-arm64" in workflow
    assert "linux-x64" not in workflow


def test_release_metadata_versions_are_0_1_37():
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    extension_package = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    extension_lock = json.loads(EXTENSION_PACKAGE_LOCK.read_text(encoding="utf-8"))

    codex_usage_lock = next(
        package for package in uv_lock["package"] if package["name"] == "codex-usage"
    )
    assert pyproject["project"]["version"] == "0.1.37"
    assert codex_usage_lock["version"] == "0.1.37"
    assert extension_package["version"] == "0.1.37"
    assert extension_lock["version"] == "0.1.37"
    assert extension_lock["packages"][""]["version"] == "0.1.37"


@pytest.mark.parametrize(
    "readme",
    (
        ROOT / "README.md",
        EXTENSION_ROOT / "README.md",
    ),
    ids=("repository", "extension"),
)
def test_task_transfer_documentation_describes_current_release_contract(readme: Path):
    transfer = markdown_section(readme, "## Task Transfer").casefold()

    assert "import tasks" in transfer and "export tasks" in transfer
    assert "fresh, empty selection" in transfer
    assert "desktop app is not required" in transfer
    assert "open vs code workspace folders" in transfer
    assert "validated local folder" in transfer
    assert "tasks/" in transfer and ("version 3" in transfer or "version-3" in transfer)
    assert "selected batch" in transfer
    assert "complete operation" in transfer or "whole operation" in transfer
    assert "task selections" in transfer and "project mappings" in transfer
    assert "not saved" in transfer or "neither" in transfer


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_0_1_34_changelog_describes_complete_release_contract(changelog: Path):
    section = markdown_section(
        changelog,
        "## 0.1.34 - 2026-07-14 - Exact Task Sync Selection",
    ).casefold()

    assert "project-grouped task picker" in section and "exact selected task thread ids" in section
    assert "tasks currently shown" in section
    assert "future tasks" in section and "explicitly selected" in section
    assert "remote-only task discovery" in section
    assert "selection schema" in section and "project/conversation" in section
    assert "setup required" in section and "does not migrate" in section
    assert "version-2 remote layout" in section
    assert "no remote cleanup or republish" in section
    assert "version-1" in section and "clean resync" in section
    assert "user-facing" in section and "technical" in section and "thread id" in section
    assert "macos apple silicon packaged inventory/push/pull verified locally" in section
    assert "windows x64 is a ci-only release gate" in section
    assert "full-jsonl" in section and "built-in codex handoff" in section


def test_workflow_uploads_artifacts_before_publishing():
    text = read_workflow()

    assert "actions/upload-artifact@v6" in text
    assert "actions/download-artifact@v6" in text
    assert "if-no-files-found: error" in text
    assert "retention-days: 14" in text


def test_publish_job_requires_secret_and_release_guard():
    text = read_workflow()

    assert "VSCE_PAT: ${{ secrets.VSCE_PAT }}" in text
    assert "    env:\n      VSCE_PAT: ${{ secrets.VSCE_PAT }}" not in text
    assert "npx vsce publish --skip-duplicate --packagePath" in text
    assert "startsWith(github.ref, 'refs/tags/v')" in text
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "inputs.publish" in text


def test_publish_job_has_release_preflight_and_rerunnable_publish():
    text = read_workflow()

    assert "fetch-depth: 0" in text
    assert "Verify release tag" in text
    assert "GITHUB_REF_NAME" in text
    assert "expected_tag=\"v${version}\"" in text
    assert "git merge-base --is-ancestor" in text
    assert "--skip-duplicate" in text
    assert text.count("npx vsce publish") == 1
