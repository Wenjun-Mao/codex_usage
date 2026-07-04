# macOS Apple Silicon Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class macOS Apple Silicon support for the Codex Usage VS Code extension while keeping the Python core, Windows package, and local-first privacy model intact.

**Architecture:** Treat `darwin-arm64` as the only macOS target. Keep the Python core as the source of truth, extend project transition evidence to understand POSIX paths, and add a macOS PyInstaller runtime at `extensions/vscode/bin/darwin-arm64/codex-usage`. Keep the VS Code wrapper thin: it selects the right bundled executable and continues spawning argument arrays with `shell: false`.

**Tech Stack:** Python 3.13, pytest, PyInstaller, TypeScript, Node test runner, VS Code `vsce`, Bash for macOS packaging, existing PowerShell script for Windows packaging.

---

## Scope Decisions

- Support Apple Silicon only: `darwin-arm64`.
- Do not add Intel Mac support: no `darwin-x64` build script, executable path, VSIX package, or documentation.
- Keep Windows support unchanged: existing `win32-x64` paths and package scripts remain valid.
- Do not port the Python core to TypeScript.
- Do not add live pricing, telemetry, or runtime downloads.

## File Structure

- Modify `src/codex_usage/project_transition_evidence.py`
  - Expand path extraction from Windows-only paths to Windows plus POSIX absolute paths.
  - Keep `extract_windows_paths` as a compatibility alias or wrapper so older imports/tests do not break.
- Modify `src/codex_usage/project_transitions.py`
  - Stop importing the Windows-specific extractor name if it is no longer used.
- Modify `tests/test_project_transitions.py`
  - Add direct POSIX path extraction tests.
- Modify `tests/test_project_transition_evidence.py`
  - Add explicit POSIX function-call and SQLite `cwd` evidence tests.
- Modify `tests/test_project_transition_detection.py`
  - Keep existing transition detection tests passing on macOS.
- Modify `tests/test_cli_transitions.py`
  - Keep CLI transition behavior passing on macOS.
- Modify `tests/test_sync.py`
  - Keep transition-aware thread filtering passing on macOS.
- Modify `extensions/vscode/src/core.ts`
  - Add `darwin-arm64` executable path support.
- Modify `extensions/vscode/src/extension.ts`
  - Update missing executable guidance to mention the macOS packaging command.
- Modify `extensions/vscode/test/core.test.js`
  - Add macOS executable path tests and macOS packaging script metadata tests.
- Create `scripts/build-macos-arm64-exe.sh`
  - Build `extensions/vscode/bin/darwin-arm64/codex-usage` with PyInstaller on Apple Silicon.
- Modify `extensions/vscode/package.json`
  - Add `build:python:mac` and `package:vsix:mac`.
  - Keep `package:vsix` mapped to Windows unless the release process explicitly changes later.
- Create `docs/adr/0010-macos-apple-silicon-vsix-runtime.md`
  - Record the Apple Silicon runtime decision.
- Modify `docs/adr/README.md`
  - Add ADR 0010.
- Modify `README.md`, `extensions/vscode/README.md`, `SUPPORT.md`, `extensions/vscode/SUPPORT.md`, `docs/release.md`, `docs/learning/05-testing-strategy.md`, and `docs/learning/06-packaging-and-release.md`
  - Replace Windows-only preview wording with Windows plus macOS Apple Silicon wording.
- Modify `CHANGELOG.md` and `extensions/vscode/CHANGELOG.md`
  - Add a release note for macOS Apple Silicon support.
- Modify `src/codex_usage/__init__.py`
  - Align `__version__` with package metadata.

---

### Task 1: Add POSIX Path Evidence Tests

**Files:**
- Modify: `tests/test_project_transitions.py`
- Modify: `tests/test_project_transition_evidence.py`

- [ ] **Step 1: Update direct path extraction imports**

In `tests/test_project_transitions.py`, change the import from:

```python
from codex_usage.project_transition_evidence import extract_windows_paths, verified_repo_observation_from_path
```

to:

```python
from codex_usage.project_transition_evidence import (
    extract_repo_paths,
    extract_windows_paths,
    verified_repo_observation_from_path,
)
```

- [ ] **Step 2: Add a direct POSIX extraction test**

Append this test after the existing Windows path extraction tests in `tests/test_project_transitions.py`:

```python
def test_extract_repo_paths_from_posix_text() -> None:
    text = (
        "Run the command in `/Users/alice/projects/ops board` and "
        "then inspect /Users/alice/projects/signoz-stack."
    )

    assert extract_repo_paths(text) == [
        "/Users/alice/projects/ops board",
        "/Users/alice/projects/signoz-stack",
    ]
```

- [ ] **Step 3: Add a compatibility test for the old function name**

Append this test after `test_extract_repo_paths_from_posix_text`:

```python
def test_extract_windows_paths_keeps_compatibility_for_posix_paths() -> None:
    assert extract_windows_paths("/Users/alice/projects/ops-board") == [
        "/Users/alice/projects/ops-board",
    ]
```

- [ ] **Step 4: Add explicit POSIX function-call evidence coverage**

Append this test to `tests/test_project_transition_evidence.py` after `test_collect_repo_path_observations_reads_function_call_workdir`:

```python
def test_collect_repo_path_observations_reads_posix_function_call_workdir(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo = tmp_path / "ops board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_jsonl(
        session_path,
        [
            _session_meta_event("thread-1"),
            _function_call_workdir_event("2026-05-23T21:06:45Z", repo),
        ],
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert len(observations) == 1
    assert observations[0].raw_path == str(repo)
    assert observations[0].project_key == "https://github.com/wenjun-mao/ops-board"
```

- [ ] **Step 5: Add explicit POSIX SQLite `cwd` evidence coverage**

Append this test to `tests/test_project_transition_evidence.py` after `test_collect_repo_path_observations_reads_state_sqlite_thread_cwd`:

```python
def test_collect_repo_path_observations_reads_posix_state_sqlite_cwd(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    repo = tmp_path / "ops board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    _write_thread_db(
        codex_home,
        cwd=str(repo),
        title="Task in ops-board",
        first_user_message="",
        preview="",
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[])

    assert len(observations) == 1
    assert observations[0].raw_path == str(repo)
    assert observations[0].source == "state_5.sqlite:threads"
```

- [ ] **Step 6: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest \
  tests/test_project_transitions.py::test_extract_repo_paths_from_posix_text \
  tests/test_project_transitions.py::test_extract_windows_paths_keeps_compatibility_for_posix_paths \
  tests/test_project_transition_evidence.py::test_collect_repo_path_observations_reads_posix_function_call_workdir \
  tests/test_project_transition_evidence.py::test_collect_repo_path_observations_reads_posix_state_sqlite_cwd \
  -q
```

Expected: FAIL because `extract_repo_paths` does not exist yet and the current extractor ignores POSIX absolute paths.

- [ ] **Step 7: Commit the failing tests**

```bash
git add tests/test_project_transitions.py tests/test_project_transition_evidence.py
git commit -m "test: cover macos project transition path evidence"
```

---

### Task 2: Implement POSIX Path Extraction

**Files:**
- Modify: `src/codex_usage/project_transition_evidence.py`
- Modify: `src/codex_usage/project_transitions.py`
- Test: `tests/test_project_transitions.py`
- Test: `tests/test_project_transition_evidence.py`
- Test: `tests/test_project_transition_detection.py`
- Test: `tests/test_cli_transitions.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Replace Windows-only extraction constants**

In `src/codex_usage/project_transition_evidence.py`, replace the current Windows-only pattern constants with:

```python
_WINDOWS_PATH_PATTERN = r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\r\n`]+[\\/])*[^\\/:*?\"<>|\r\n`]+"
_DELIMITED_WINDOWS_PATH_PATTERN = re.compile(rf"(?P<delimiter>[`\"])(?P<path>{_WINDOWS_PATH_PATTERN})(?P=delimiter)")
_BARE_WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\s\r\n`]+[\\/])*[^\\/:*?\"<>|\s\r\n`]+")

_POSIX_PATH_PATTERN = r"/(?:[^/\0\r\n`\"<>|]+/)*[^/\0\r\n`\"<>|]+"
_DELIMITED_POSIX_PATH_PATTERN = re.compile(rf"(?P<delimiter>[`\"])(?P<path>{_POSIX_PATH_PATTERN})(?P=delimiter)")
_BARE_POSIX_PATH_PATTERN = re.compile(r"(?<!:)/(?:[^/\s\r\n`\"<>|]+/)*[^/\s\r\n`\"<>|]+")
_TRAILING_PATH_PUNCTUATION = ".,;:)]}'\""
```

- [ ] **Step 2: Replace `extract_windows_paths` with a cross-platform extractor and compatibility wrapper**

In `src/codex_usage/project_transition_evidence.py`, replace the existing `extract_windows_paths` function with:

```python
def extract_repo_paths(text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    candidates: list[tuple[int, str, bool]] = []
    delimited_spans: list[tuple[int, int]] = []

    stripped = text.strip()
    if stripped.startswith("/"):
        candidates.append((0, stripped, False))

    for pattern in (_DELIMITED_WINDOWS_PATH_PATTERN, _DELIMITED_POSIX_PATH_PATTERN):
        for match in pattern.finditer(text):
            delimited_spans.append(match.span())
            candidates.append((match.start("path"), match.group("path"), False))

    for pattern in (_BARE_WINDOWS_PATH_PATTERN, _BARE_POSIX_PATH_PATTERN):
        for match in pattern.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in delimited_spans):
                continue
            candidates.append((match.start(), match.group(0), True))

    for _, candidate, trim_trailing_punctuation in sorted(candidates, key=lambda item: item[0]):
        value = candidate.rstrip(_TRAILING_PATH_PUNCTUATION) if trim_trailing_punctuation else candidate
        if value and value not in seen:
            seen.add(value)
            paths.append(value)
    return paths


def extract_windows_paths(text: str) -> list[str]:
    return extract_repo_paths(text)
```

- [ ] **Step 3: Use the new extractor in JSONL evidence collection**

In `_collect_jsonl_observations`, replace:

```python
for raw_path in extract_windows_paths(text):
```

with:

```python
for raw_path in extract_repo_paths(text):
```

- [ ] **Step 4: Use the new extractor in SQLite evidence collection**

In `_collect_state_sqlite_observations`, replace:

```python
for raw_path in extract_windows_paths(text):
```

with:

```python
for raw_path in extract_repo_paths(text):
```

- [ ] **Step 5: Remove only extractor imports that are no longer used**

In `src/codex_usage/project_transitions.py`, keep any imports that are still used directly or re-exported for existing callers. At minimum, preserve `collect_repo_path_observations`, because `cli.py`, `session_cache.py`, and `threads.py` import it from `codex_usage.project_transitions`.

If the import currently looks like:

```python
from codex_usage.project_transition_evidence import (
    RepoPathObservation,
    collect_repo_path_observations,
    extract_windows_paths,
    verified_repo_observation_from_path,
)
```

change it to:

```python
from codex_usage.project_transition_evidence import (
    RepoPathObservation,
    collect_repo_path_observations,
)
```

Then confirm no removed imported names from `project_transition_evidence` are used in this file.

- [ ] **Step 6: Run focused extraction and evidence tests**

Run:

```bash
uv run pytest tests/test_project_transitions.py tests/test_project_transition_evidence.py -q
```

Expected: PASS.

- [ ] **Step 7: Run transition-dependent tests that failed on macOS**

Run:

```bash
uv run pytest \
  tests/test_cli_transitions.py \
  tests/test_project_transition_detection.py \
  tests/test_sync.py::test_list_threads_filters_by_transition_target_project \
  -q
```

Expected: PASS.

- [ ] **Step 8: Run the full Python suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS with all Python tests passing on macOS.

- [ ] **Step 9: Commit POSIX extraction support**

```bash
git add src/codex_usage/project_transition_evidence.py src/codex_usage/project_transitions.py
git commit -m "fix: support macos paths in project transition evidence"
```

---

### Task 3: Add macOS Apple Silicon Executable Resolution

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Update the executable path test first**

In `extensions/vscode/test/core.test.js`, replace the test named `bundledExecutablePath resolves Windows x64 executable and rejects unsupported platforms` with:

```javascript
test("bundledExecutablePath resolves supported bundled executables and rejects unsupported platforms", () => {
  assert.equal(
    bundledExecutablePath("C:/extension", "win32", "x64"),
    path.join("C:/extension", "bin", "win32-x64", "codex-usage.exe"),
  );
  assert.equal(
    bundledExecutablePath("/Users/alice/.vscode/extensions/codex-usage", "darwin", "arm64"),
    path.join("/Users/alice/.vscode/extensions/codex-usage", "bin", "darwin-arm64", "codex-usage"),
  );
  assert.throws(() => bundledExecutablePath("/extension", "darwin", "x64"), /Unsupported platform/);
  assert.throws(() => bundledExecutablePath("/extension", "linux", "x64"), /Unsupported platform/);
});
```

- [ ] **Step 2: Run the TypeScript test and verify it fails**

Run from `extensions/vscode`:

```bash
npm test -- --test-name-pattern bundledExecutablePath
```

Expected: FAIL because `bundledExecutablePath` does not support `darwin-arm64` yet.

- [ ] **Step 3: Add `darwin-arm64` support**

In `extensions/vscode/src/core.ts`, replace `bundledExecutablePath` with:

```typescript
export function bundledExecutablePath(extensionPath: string, platform: string, arch: string): string {
  if (platform === "win32" && arch === "x64") {
    return path.join(extensionPath, "bin", "win32-x64", "codex-usage.exe");
  }
  if (platform === "darwin" && arch === "arm64") {
    return path.join(extensionPath, "bin", "darwin-arm64", "codex-usage");
  }
  throw new Error(
    `Unsupported platform: ${platform}-${arch}. This VSIX currently bundles Windows x64 and macOS Apple Silicon.`,
  );
}
```

- [ ] **Step 4: Update missing executable guidance**

In `extensions/vscode/src/extension.ts`, replace the error text in `resolveBundledExecutable`:

```typescript
        "Rebuild the Windows VSIX with `npm run package:vsix:win`.",
```

with:

```typescript
        "Rebuild the VSIX for this platform with `npm run package:vsix:win` or `npm run package:vsix:mac`.",
```

- [ ] **Step 5: Run the TypeScript tests**

Run from `extensions/vscode`:

```bash
npm test
```

Expected: PASS.

- [ ] **Step 6: Commit executable resolution**

```bash
git add extensions/vscode/src/core.ts extensions/vscode/src/extension.ts extensions/vscode/test/core.test.js
git commit -m "feat: resolve bundled executable on macos arm64"
```

---

### Task 4: Add Apple Silicon Build And VSIX Package Scripts

**Files:**
- Create: `scripts/build-macos-arm64-exe.sh`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add failing package metadata tests**

Append this test after `windows VSIX package script creates the release output directory` in `extensions/vscode/test/core.test.js`:

```javascript
test("macos Apple Silicon VSIX package script creates the release output directory", () => {
  assert.match(packageJson.scripts["build:python:mac"], /build-macos-arm64-exe\.sh/);
  assert.match(packageJson.scripts["package:vsix:mac"], /mkdir -p \.\.\/\.\.\/output\/releases/);
  assert.match(packageJson.scripts["package:vsix:mac"], /npm run build:python:mac/);
  assert.match(packageJson.scripts["package:vsix:mac"], /--target darwin-arm64/);
  assert.match(
    packageJson.scripts["package:vsix:mac"],
    /--out \.\.\/\.\.\/output\/releases\/codex-usage-dashboard-darwin-arm64\.vsix/,
  );
});
```

- [ ] **Step 2: Run the package metadata test and verify it fails**

Run from `extensions/vscode`:

```bash
npm test -- --test-name-pattern "macos Apple Silicon VSIX"
```

Expected: FAIL because `build:python:mac` and `package:vsix:mac` do not exist yet.

- [ ] **Step 3: Create the macOS build script**

Create `scripts/build-macos-arm64-exe.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist_dir="$repo_root/extensions/vscode/bin/darwin-arm64"
work_dir="$repo_root/build/pyinstaller-darwin-arm64"
entry_point="$repo_root/src/codex_usage/__main__.py"
exe_path="$dist_dir/codex-usage"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This script must run on macOS Apple Silicon (darwin-arm64)." >&2
  exit 2
fi

mkdir -p "$dist_dir" "$work_dir"
rm -f "$exe_path"

cd "$repo_root"
uv run --group package pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --console \
  --name codex-usage \
  --paths src \
  --distpath "$dist_dir" \
  --workpath "$work_dir" \
  --specpath "$work_dir" \
  "$entry_point"

if [[ ! -f "$exe_path" ]]; then
  echo "Expected executable was not created: $exe_path" >&2
  exit 1
fi

chmod +x "$exe_path"
"$exe_path" --help >/dev/null
```

- [ ] **Step 4: Mark the script executable**

Run:

```bash
chmod +x scripts/build-macos-arm64-exe.sh
```

Expected: `git status --short` shows the new script as added and executable after staging.

- [ ] **Step 5: Add package scripts**

In `extensions/vscode/package.json`, add these scripts next to the existing Windows scripts:

```json
"build:python:mac": "bash ../../scripts/build-macos-arm64-exe.sh",
"package:vsix:mac": "mkdir -p ../../output/releases && npm run build:python:mac && vsce package --target darwin-arm64 --out ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix",
```

Keep the existing scripts:

```json
"build:python:win": "powershell -NoProfile -ExecutionPolicy Bypass -File ..\\..\\scripts\\build-windows-exe.ps1",
"package:vsix": "npm run package:vsix:win",
"package:vsix:win": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"New-Item -ItemType Directory -Force ..\\..\\output\\releases | Out-Null\" && npm run build:python:win && vsce package --target win32-x64 --out ../../output/releases/codex-usage-dashboard-win32-x64.vsix",
```

- [ ] **Step 6: Run TypeScript tests**

Run from `extensions/vscode`:

```bash
npm test
```

Expected: PASS.

- [ ] **Step 7: Build the macOS executable**

Run from `extensions/vscode`:

```bash
npm run build:python:mac
```

Expected:

```text
extensions/vscode/bin/darwin-arm64/codex-usage
```

exists and `extensions/vscode/bin/darwin-arm64/codex-usage --help` exits with code 0.

- [ ] **Step 8: Package the macOS VSIX**

Run from `extensions/vscode`:

```bash
npm run package:vsix:mac
```

Expected:

```text
output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

is created.

- [ ] **Step 9: Inspect the macOS VSIX**

Run from the repository root:

```bash
tar -tf output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

Expected output includes:

```text
extension/bin/darwin-arm64/codex-usage
extension/out/core.js
extension/out/extension.js
extension/package.json
extension/media/icon.png
extension/README.md
extension/CHANGELOG.md
extension/SUPPORT.md
extension/LICENSE.txt
```

Expected output does not include:

```text
extension/src/
extension/test/
extension/node_modules/
extension/.vscode/
```

- [ ] **Step 10: Commit macOS packaging**

```bash
git add scripts/build-macos-arm64-exe.sh extensions/vscode/package.json extensions/vscode/test/core.test.js
git commit -m "build: package vscode extension for macos arm64"
```

---

### Task 5: Update Public Docs And ADRs

**Files:**
- Create: `docs/adr/0010-macos-apple-silicon-vsix-runtime.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `SUPPORT.md`
- Modify: `extensions/vscode/SUPPORT.md`
- Modify: `docs/release.md`
- Modify: `docs/learning/05-testing-strategy.md`
- Modify: `docs/learning/06-packaging-and-release.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `src/codex_usage/__init__.py`

- [ ] **Step 1: Add the macOS runtime ADR**

Create `docs/adr/0010-macos-apple-silicon-vsix-runtime.md`:

```markdown
# ADR 0010: macOS Apple Silicon VSIX Runtime

Status: Accepted

Date: 2026-07-04

## Context

The first Marketplace preview bundled a Windows x64 PyInstaller executable. macOS users need the same self-contained VS Code extension experience without requiring Python, uv, or this repository at runtime.

Apple is phasing out Intel Mac support, and this project does not plan to support Intel macOS packages.

## Decision

Bundle a PyInstaller-built `codex-usage` executable for `darwin-arm64` at `extensions/vscode/bin/darwin-arm64/codex-usage` and package it with `vsce --target darwin-arm64`.

Keep Windows x64 packaging unchanged. Do not add `darwin-x64`.

## Alternatives Considered

- Require macOS users to install Python and uv. This keeps packaging simple, but gives Marketplace users a worse runtime story than Windows users.
- Build both Apple Silicon and Intel macOS packages. Intel support adds release and test surface for a platform Apple is actively phasing out.
- Port the Python core to TypeScript. This duplicates mature accounting, cache, pricing, transition, and sync logic.

## Consequences

macOS Apple Silicon users get a self-contained VSIX. The release process now has separate Windows and macOS package commands. Intel Mac users receive a clear unsupported-platform error.

## Guardrails

Do not download a runtime on first use. Do not support Intel Mac unless a future ADR reverses this decision. Keep TypeScript responsible only for VS Code orchestration and platform executable selection.
```

- [ ] **Step 2: Register ADR 0010**

In `docs/adr/README.md`, add:

```markdown
| [0010](0010-macos-apple-silicon-vsix-runtime.md) | Bundle a macOS Apple Silicon executable in the VSIX. |
```

after ADR 0009.

- [ ] **Step 3: Update root README support language**

In `README.md`, replace Windows-only preview language with:

```markdown
- A Windows x64 and macOS Apple Silicon VS Code extension preview that bundles the Python CLI.
```

Replace the `## Windows VS Code Preview` section heading with:

```markdown
## VS Code Preview Packages
```

Replace the first preview paragraph with:

```markdown
The current preview packages support Windows x64 and macOS Apple Silicon. Each package is self-contained at runtime and does not require Python, `uv`, or this repository after installation.
```

Add a macOS package command block after the Windows command block:

```bash
cd extensions/vscode
npm run package:vsix:mac
code --install-extension ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```

Replace "The Windows VS Code preview stores..." with:

```markdown
The VS Code preview stores a local SQLite cache under VS Code global extension storage.
```

Replace "The Windows VS Code beta can sync..." with:

```markdown
The VS Code preview can sync selected Codex conversations through a bring-your-own local sync folder such as iCloud Drive, OneDrive, Dropbox, Syncthing, or a network drive.
```

- [ ] **Step 4: Update extension README support language**

In `extensions/vscode/README.md`, replace the first line after the title with:

```markdown
Windows x64 and macOS Apple Silicon Preview VS Code extension for viewing local Codex token usage, project rollups, Codex credits, and API-equivalent cost estimates.
```

Replace the preview status paragraph with:

```markdown
This Marketplace preview supports Windows x64 and macOS Apple Silicon. The installed extension bundles `codex-usage.exe` on Windows and `codex-usage` on macOS, and does not require Python, `uv`, or this repository at runtime. Intel macOS is not supported.
```

Replace the Windows install section with:

````markdown
## Preview Install

Windows x64:

```powershell
code --install-extension output\releases\codex-usage-dashboard-win32-x64.vsix --force
```

macOS Apple Silicon:

```bash
code --install-extension output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```
````

In the troubleshooting sessions path bullet, include POSIX path examples:

```markdown
- If no usage appears, confirm Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
```

In the development command block, add:

```bash
npm run package:vsix:mac
```

- [ ] **Step 5: Update support docs**

In `SUPPORT.md` and `extensions/vscode/SUPPORT.md`, replace the Windows-only OS bullet with:

```markdown
- Operating system and CPU architecture, for example Windows x64 or macOS Apple Silicon.
```

Replace the session path bullet with:

```markdown
- Whether Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
```

- [ ] **Step 6: Update release checklist**

In `docs/release.md`, replace Windows-only target language with Windows plus macOS Apple Silicon language. Add build commands:

```powershell
npm run package:vsix:win
```

and:

```bash
npm run package:vsix:mac
```

Add expected macOS VSIX output:

```text
output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

Add expected macOS archive member:

```text
extension/bin/darwin-arm64/codex-usage
```

Keep the Windows expected archive member:

```text
extension/bin/win32-x64/codex-usage.exe
```

- [ ] **Step 7: Update learning docs**

In `docs/learning/05-testing-strategy.md`, add macOS verification commands after the Windows commands:

```bash
cd extensions/vscode
npm test
npm run package:vsix:mac
```

In `docs/learning/06-packaging-and-release.md`, add a `Bundled macOS Runtime` section:

````markdown
## Bundled macOS Runtime

The macOS Apple Silicon preview VSIX bundles:

```text
extensions/vscode/bin/darwin-arm64/codex-usage
```

The executable is built from the Python core with PyInstaller on Apple Silicon. Intel macOS is intentionally unsupported.
````

- [ ] **Step 8: Update changelogs**

At the top of `CHANGELOG.md`, add:

```markdown
## 0.1.31 - macOS Apple Silicon Preview

- Added macOS Apple Silicon VS Code packaging with a bundled `codex-usage` executable.
- Added POSIX path evidence for automatic project transition detection on macOS.
- Kept Windows x64 packaging unchanged and documented Intel macOS as unsupported.
```

At the top of `extensions/vscode/CHANGELOG.md`, add:

```markdown
## 0.1.31

- Added macOS Apple Silicon preview packaging with a bundled `codex-usage` executable.
- Kept Windows x64 packaging unchanged.
```

- [ ] **Step 9: Align Python package version**

In `src/codex_usage/__init__.py`, replace:

```python
__version__ = "0.1.19"
```

with:

```python
__version__ = "0.1.31"
```

In `pyproject.toml`, replace:

```toml
version = "0.1.30"
```

with:

```toml
version = "0.1.31"
```

In `extensions/vscode/package.json`, replace:

```json
"version": "0.1.30",
```

with:

```json
"version": "0.1.31",
```

- [ ] **Step 10: Run documentation wording scan**

Run:

```bash
rg -n "Windows x64 only|Windows-only|Linux and macOS packages are planned|First preview target is Windows x64 only|Rebuild the Windows VSIX" README.md docs extensions/vscode src scripts
```

Expected: no matches except historical ADR 0006 language that is explicitly superseded by ADR 0010.

- [ ] **Step 11: Commit docs and version updates**

```bash
git add \
  docs/adr/0010-macos-apple-silicon-vsix-runtime.md \
  docs/adr/README.md \
  README.md \
  extensions/vscode/README.md \
  SUPPORT.md \
  extensions/vscode/SUPPORT.md \
  docs/release.md \
  docs/learning/05-testing-strategy.md \
  docs/learning/06-packaging-and-release.md \
  CHANGELOG.md \
  extensions/vscode/CHANGELOG.md \
  src/codex_usage/__init__.py \
  pyproject.toml \
  extensions/vscode/package.json
git commit -m "docs: document macos apple silicon preview"
```

---

### Task 6: Final Verification

**Files:**
- No planned source edits.

- [ ] **Step 1: Run the full Python suite**

Run from the repository root:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run the VS Code wrapper tests**

Run from `extensions/vscode`:

```bash
npm test
```

Expected: PASS.

- [ ] **Step 3: Build the macOS Apple Silicon executable**

Run from `extensions/vscode`:

```bash
npm run build:python:mac
```

Expected:

```text
extensions/vscode/bin/darwin-arm64/codex-usage
```

exists and is executable.

- [ ] **Step 4: Smoke the bundled macOS executable**

Run from the repository root:

```bash
extensions/vscode/bin/darwin-arm64/codex-usage --help
extensions/vscode/bin/darwin-arm64/codex-usage storage snapshot --json
```

Expected: both commands exit with code 0. The storage snapshot may report zero JSONL files if the machine has no local Codex sessions.

- [ ] **Step 5: Build the macOS VSIX**

Run from `extensions/vscode`:

```bash
npm run package:vsix:mac
```

Expected:

```text
../../output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

is created.

- [ ] **Step 6: Inspect the macOS VSIX contents**

Run from the repository root:

```bash
tar -tf output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

Expected: includes `extension/bin/darwin-arm64/codex-usage` and excludes `extension/src/`, `extension/test/`, and `extension/node_modules/`.

- [ ] **Step 7: Verify the working tree**

Run:

```bash
git status --short --branch
```

Expected: clean working tree on the feature branch after all commits.

---

## Rollback Plan

If macOS packaging fails late:

1. Keep Task 1 and Task 2 if Python tests pass, because POSIX transition evidence is a valid Mac core fix.
2. Revert Task 3 through Task 5 commits to remove VS Code macOS packaging claims.
3. Leave ADR 0010 out of the release until a bundled `darwin-arm64` executable can be built and packaged.

## Self-Review

- Spec coverage: This plan covers POSIX transition evidence, macOS Apple Silicon executable resolution, Apple Silicon PyInstaller packaging, VSIX packaging, docs/release updates, version alignment, and final verification.
- Placeholder scan: No placeholder markers or incomplete instruction steps remain.
- Type consistency: `darwin-arm64`, `codex-usage`, `build:python:mac`, and `package:vsix:mac` are used consistently.
- Scope check: Intel macOS is explicitly out of scope.
