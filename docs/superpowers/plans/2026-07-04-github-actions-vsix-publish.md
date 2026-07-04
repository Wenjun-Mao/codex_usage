# GitHub Actions VSIX Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions workflow that builds both platform-specific VSIX packages and publishes them to the VS Code Marketplace when explicitly requested.

**Architecture:** A workflow in `.github/workflows/package-vsix.yml` runs separate Windows x64 and macOS Apple Silicon packaging jobs, uploads both VSIX artifacts, and gates Marketplace publishing behind either a `v*` tag push or an explicit manual `publish` input on `main`. A focused Python regression test checks that the workflow keeps the required runner labels, package commands, artifact paths, and publish guard.

**Tech Stack:** GitHub Actions, Windows/macOS hosted runners, Python 3.13, `uv`, Node.js 24, npm, `vsce`, PyInstaller, pytest.

---

## File Structure

- Create `.github/workflows/package-vsix.yml`: orchestrates native Windows/macOS builds, artifact upload, and guarded Marketplace publish.
- Create `tests/test_github_actions_workflow.py`: text-level regression tests for critical workflow behavior.
- Modify `docs/release.md`: documents the new CI packaging/publishing path and the `VSCE_PAT` secret.

### Task 1: Add Workflow Regression Test And CI Workflow

**Files:**
- Create: `tests/test_github_actions_workflow.py`
- Create: `.github/workflows/package-vsix.yml`

- [ ] **Step 1: Write the failing workflow regression test**

Create `tests/test_github_actions_workflow.py` with this content:

```python
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
    assert "npx vsce publish --packagePath" in text
    assert "startsWith(github.ref, 'refs/tags/v')" in text
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "inputs.publish" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py -q
```

Expected: FAIL with `FileNotFoundError` for `.github/workflows/package-vsix.yml`.

- [ ] **Step 3: Add the GitHub Actions workflow**

Create `.github/workflows/package-vsix.yml` with this content:

```yaml
name: Package and Publish VSIX

on:
  workflow_dispatch:
    inputs:
      publish:
        description: "Publish the generated VSIX files to the VS Code Marketplace"
        required: true
        type: boolean
        default: false
  push:
    tags:
      - "v*"

permissions:
  contents: read

concurrency:
  group: vsix-release-${{ github.ref }}
  cancel-in-progress: false

env:
  NODE_VERSION: "24"
  PYTHON_VERSION: "3.13"

jobs:
  windows:
    name: Build Windows x64 VSIX
    runs-on: windows-2025

    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        uses: astral-sh/setup-uv@v8.2.0
        with:
          enable-cache: true

      - name: Set up Node.js
        uses: actions/setup-node@v6
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: npm
          cache-dependency-path: extensions/vscode/package-lock.json

      - name: Run Python tests
        run: uv run pytest -q

      - name: Install VS Code extension dependencies
        working-directory: extensions/vscode
        run: npm ci

      - name: Run VS Code extension tests
        working-directory: extensions/vscode
        run: npm test

      - name: Package Windows VSIX
        working-directory: extensions/vscode
        run: npm run package:vsix:win

      - name: Upload Windows VSIX
        uses: actions/upload-artifact@v6
        with:
          name: codex-usage-dashboard-win32-x64
          path: output/releases/codex-usage-dashboard-win32-x64.vsix
          if-no-files-found: error
          retention-days: 14

  macos:
    name: Build macOS Apple Silicon VSIX
    runs-on: macos-26

    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        uses: astral-sh/setup-uv@v8.2.0
        with:
          enable-cache: true

      - name: Set up Node.js
        uses: actions/setup-node@v6
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: npm
          cache-dependency-path: extensions/vscode/package-lock.json

      - name: Run Python tests
        run: uv run pytest -q

      - name: Install VS Code extension dependencies
        working-directory: extensions/vscode
        run: npm ci

      - name: Run VS Code extension tests
        working-directory: extensions/vscode
        run: npm test

      - name: Package macOS Apple Silicon VSIX
        working-directory: extensions/vscode
        run: npm run package:vsix:mac

      - name: Upload macOS Apple Silicon VSIX
        uses: actions/upload-artifact@v6
        with:
          name: codex-usage-dashboard-darwin-arm64
          path: output/releases/codex-usage-dashboard-darwin-arm64.vsix
          if-no-files-found: error
          retention-days: 14

  publish:
    name: Publish VSIX packages
    needs:
      - windows
      - macos
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v') || (github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && inputs.publish)
    env:
      VSCE_PAT: ${{ secrets.VSCE_PAT }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up Node.js
        uses: actions/setup-node@v6
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: npm
          cache-dependency-path: extensions/vscode/package-lock.json

      - name: Install VS Code extension dependencies
        working-directory: extensions/vscode
        run: npm ci

      - name: Download packaged VSIX artifacts
        uses: actions/download-artifact@v6
        with:
          path: output/releases
          merge-multiple: true

      - name: Verify publish inputs
        run: |
          test -n "$VSCE_PAT"
          test -f output/releases/codex-usage-dashboard-win32-x64.vsix
          test -f output/releases/codex-usage-dashboard-darwin-arm64.vsix

      - name: Publish Windows x64 VSIX
        working-directory: extensions/vscode
        run: npx vsce publish --packagePath ../../output/releases/codex-usage-dashboard-win32-x64.vsix

      - name: Publish macOS Apple Silicon VSIX
        working-directory: extensions/vscode
        run: npx vsce publish --packagePath ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

- [ ] **Step 4: Run the workflow regression test**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py -q
```

Expected: PASS with `4 passed`.

- [ ] **Step 5: Validate workflow YAML parses**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/package-vsix.yml"); puts "workflow YAML parsed"'
```

Expected: PASS with `workflow YAML parsed`.

- [ ] **Step 6: Commit the workflow and regression test**

Run:

```bash
git add .github/workflows/package-vsix.yml tests/test_github_actions_workflow.py
git commit -m "ci: build and publish platform vsix packages"
```

### Task 2: Document CI Packaging And Publishing

**Files:**
- Modify: `docs/release.md`

- [ ] **Step 1: Update release documentation**

In `docs/release.md`, add a new section after `## Build And Test`:

```markdown
## GitHub Actions Release

The repository has a `Package and Publish VSIX` workflow that builds both platform packages on native GitHub-hosted runners.

Use the manual workflow trigger with `publish=false` to build and inspect artifacts without publishing. Use `publish=true` from `main` to publish both generated VSIX files to the VS Code Marketplace. Pushing a release tag such as `v0.1.32` also builds and publishes both packages.

The workflow requires the repository Actions secret `VSCE_PAT`. The token must have Marketplace `Manage` permission for publisher `wenjun-mao`.
```

- [ ] **Step 2: Run a documentation grep check**

Run:

```bash
rg -n "Package and Publish VSIX|VSCE_PAT|publish=false|v0\\.1\\.32" docs/release.md
```

Expected: each search term appears in the new `GitHub Actions Release` section.

- [ ] **Step 3: Commit the docs update**

Run:

```bash
git add docs/release.md
git commit -m "docs: document github actions vsix release workflow"
```

### Task 3: Full Local Verification

**Files:**
- Verify: `.github/workflows/package-vsix.yml`
- Verify: `tests/test_github_actions_workflow.py`
- Verify: `docs/release.md`

- [ ] **Step 1: Run Python tests**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass, including `tests/test_github_actions_workflow.py`.

- [ ] **Step 2: Run VS Code extension tests**

Run:

```bash
zsh -ilc 'cd /Users/wjmao/projects/codex_usage/extensions/vscode && npm test'
```

Expected: all extension tests pass.

- [ ] **Step 3: Validate workflow YAML parses**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/package-vsix.yml"); puts "workflow YAML parsed"'
```

Expected: PASS with `workflow YAML parsed`.

- [ ] **Step 4: Verify the Marketplace PAT is available locally without printing it**

Run:

```bash
zsh -ilc 'cd /Users/wjmao/projects/codex_usage/extensions/vscode && set -a && source ../../.env && set +a && test -n "$VSCE_PAT" && npx vsce verify-pat wenjun-mao'
```

Expected: PASS with `The Personal Access Token verification succeeded for the publisher 'wenjun-mao'.`

- [ ] **Step 5: Verify GitHub has the Actions secret metadata**

Run:

```bash
gh secret list --repo Wenjun-Mao/codex_usage | rg '^VSCE_PAT\\s'
```

Expected: PASS and prints only secret metadata, not the token value.

- [ ] **Step 6: Check the final diff**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits 0, and `git status --short` only shows intentional committed-ahead state or a clean tree after final commit.

### Task 4: Push And Remote Smoke

**Files:**
- Verify remote workflow: `.github/workflows/package-vsix.yml`

- [ ] **Step 1: Push `main`**

Run:

```bash
git push origin main
```

Expected: push succeeds.

- [ ] **Step 2: Run artifact-only workflow from GitHub Actions**

Run:

```bash
gh workflow run "Package and Publish VSIX" --repo Wenjun-Mao/codex_usage --ref main -f publish=false
```

Expected: workflow dispatch is accepted.

- [ ] **Step 3: Watch the workflow run**

Run:

```bash
gh run watch --repo Wenjun-Mao/codex_usage --exit-status
```

Expected: the workflow succeeds, both package jobs pass, and the publish job is skipped because `publish=false`.

- [ ] **Step 4: Confirm artifacts are present**

Run:

```bash
gh run list --repo Wenjun-Mao/codex_usage --workflow "Package and Publish VSIX" --limit 1
```

Expected: the latest run is completed successfully. Open the run in GitHub if artifact download inspection is needed.
