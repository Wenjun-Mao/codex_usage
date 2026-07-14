import json
import re
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
PACKAGED_SYNC_SMOKE = ROOT / "scripts" / "smoke-test-packaged-sync.py"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
EXTENSION_ROOT = ROOT / "extensions" / "vscode"
EXTENSION_PACKAGE = EXTENSION_ROOT / "package.json"
EXTENSION_PACKAGE_LOCK = EXTENSION_ROOT / "package-lock.json"
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


def test_packaged_sync_smoke_exercises_inventory_and_exact_thread_sync():
    text = PACKAGED_SYNC_SMOKE.read_text(encoding="utf-8")

    assert '["sync", "inventory", "--sync-dir"' in text
    assert '["sync", "run", "--sync-dir"' in text
    assert 'local_inventory["projects"][0]["tasks"][0]["availability"] == "local"' in text
    assert 'remote_inventory["projects"][0]["tasks"][0]["availability"] == "remote"' in text
    assert "inventory=local,remote pushed=1 pulled=1 format_version=2" in text


def test_release_metadata_versions_are_0_1_34():
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    extension_package = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    extension_lock = json.loads(EXTENSION_PACKAGE_LOCK.read_text(encoding="utf-8"))

    codex_usage_lock = next(
        package for package in uv_lock["package"] if package["name"] == "codex-usage"
    )
    assert pyproject["project"]["version"] == "0.1.34"
    assert codex_usage_lock["version"] == "0.1.34"
    assert extension_package["version"] == "0.1.34"
    assert extension_lock["version"] == "0.1.34"
    assert extension_lock["packages"][""]["version"] == "0.1.34"


@pytest.mark.parametrize(
    "readme",
    (ROOT / "README.md", EXTENSION_ROOT / "README.md"),
    ids=("repository", "extension"),
)
def test_sync_documentation_describes_exact_task_selection(readme: Path):
    text = readme.read_text(encoding="utf-8")

    assert "one project-grouped `Select Tasks` picker" in text
    assert "current-task shortcuts" in text
    assert "Remote-only tasks" in text
    assert "Future tasks" in text
    assert "**Setup required**" in text
    assert "no remote cleanup or republish" in text
    assert "technical thread id" in text
    assert "full JSONL" in text


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
