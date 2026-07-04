from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"


def read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_has_manual_and_tag_triggers():
    text = read_workflow()

    assert "workflow_dispatch:" in text
    assert "publish:" in text
    assert "type: boolean" in text
    assert "default: false" in text
    assert "push:" in text
    assert '"v*"' in text


def test_workflow_builds_platform_vsix_files_on_native_runners():
    text = read_workflow()

    assert "runs-on: windows-2025" in text
    assert "runs-on: macos-26" in text
    assert "npm run package:vsix:win" in text
    assert "npm run package:vsix:mac" in text
    assert "codex-usage-dashboard-win32-x64.vsix" in text
    assert "codex-usage-dashboard-darwin-arm64.vsix" in text


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
