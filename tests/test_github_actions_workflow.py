import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
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
