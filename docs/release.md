# 2.0 Distribution Checklist

Version 2.0 publishes standalone macOS Apple Silicon and Windows x64 VSIX
packages to the VS Code Marketplace. Each VSIX bundles its matching collector
and does not require the native application.

The same workflow builds unsigned native DMG and NSIS previews with SHA-256
integrity metadata. Native previews are retained as GitHub Actions artifacts for
evaluation; they are not stable GitHub Release assets and have no automatic
update channel. Linux, Intel macOS, and Windows ARM64 are not release targets.

## Required Secret

- `VSCE_PAT` with Manage permission for publisher `wenjun-mao`.

The 2.0 release workflow has no Apple Developer, Azure Artifact Signing, or Tauri
updater-signing dependency.

## Local Gates

Run from the repository root:

```bash
uv sync --all-groups
uv run pytest -q
uv run ruff check .
```

Native frontend and Rust host:

```bash
cd apps/desktop
npm ci
npm test
npm run build
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo test --manifest-path src-tauri/Cargo.toml --all-targets
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
```

macOS packaged sidecar:

```bash
./scripts/build-agent-macos-arm64.sh
```

Standalone VS Code extension:

```bash
cd extensions/vscode
npm ci
npm test
npm run package:vsix:mac
```

The package audit must show the matching collector executable and exclude the
other platform's binary, Python source, caches, and tests. Windows packaging is
performed on the Windows CI runner.

### 2.0.0 performance evidence

The 2026-09-02 candidate was checked against a 33 GiB, 1,325-file local corpus
through an isolated ledger. One bounded baseline slice completed in 0.52 seconds,
reported 115 MiB of source reads, and correctly exposed 0.19% coverage with all
unscheduled files and bytes still pending. A separate 100-file live subset
completed its baseline in 0.15 seconds; the immediately repeated unchanged
capture completed in 0.01 seconds with 100 files reused and zero source bytes
read. Timings are machine-specific evidence, not CI thresholds.

## Visual Gate

Run the native frontend fixture through Playwright at desktop and narrow window
sizes (1440 x 900 and 760 x 900). Confirm:

- the sidebar and Capture Now remain usable without overlap;
- Usage clearly shows last/next capture, pending work, incomplete baseline, and
  stale-source states;
- report content and tooltips are not clipped;
- Task Storage exposes Analyze and cancellation without unrelated operations;
- Task Transfer has separate one-project and task-selection stages, zero default
  task selection, project-only search, Back navigation, and explicit destination;
- Settings expose 1-1,440 minutes, Manual Only, background registration, Codex
  home switching, daily updates, Unregister, and Reset Local Data;
- no synthetic screenshot contains personal paths or corpus data.

Regenerate and review:

```bash
uv run playwright install chromium
uv run python scripts/generate_marketplace_screenshot.py
uv run python scripts/generate_marketplace_screenshot.py --check
```

Visually review both generated images before committing them. The automated
gate catches geometry and overflow regressions, but it does not replace a human
check for hierarchy, readability, and representative product copy.

## Non-Publishing Native Gate

Push the candidate commit to `main`, then dispatch:

```bash
gh workflow run package-vsix.yml --ref main -f publish=false
```

Require all five jobs to pass before publication:

- core/release-contract validation;
- macOS Apple Silicon VSIX packaging with its bundled collector;
- Windows x64 VSIX packaging with its bundled collector;
- macOS ARM64 PyInstaller, frontend, Rust, and unsigned DMG preview;
- Windows x64 PyInstaller, frontend, Rust, and unsigned NSIS preview.

The two native jobs upload 14-day unsigned preview artifacts and integrity
metadata. They validate the optional app but do not gate Marketplace publishing
as a runtime dependency.

## Marketplace Publication

Confirm all Python, npm, Cargo, Tauri, and lockfile versions are `2.0.1`, both
changelogs have a dated `2.0.1` entry, and the candidate commit is contained in
`origin/main`.

The only valid release tag for this version is `v2.0.1`. Create and push that
exact tag after the non-publishing gate succeeds:

```bash
git tag v2.0.1
git push origin v2.0.1
```

The tag reruns every platform gate and publishes these immutable Marketplace
packages:

```text
codex-usage-companion-darwin-arm64.vsix
codex-usage-companion-win32-x64.vsix
```

The native jobs also produce these run-scoped artifacts:

```text
Codex-Usage-2.0.1-macos-arm64-unsigned-preview.dmg
Codex-Usage-2.0.1-windows-x64-unsigned-preview-setup.exe
preview-integrity.json
SHA256SUMS.txt
```

The workflow does not create a GitHub Release. Marketplace publication is
rerunnable because VSCE uses `--skip-duplicate`.

## Clean-Install Acceptance

On clean macOS Apple Silicon and Windows x64 accounts, install the matching VSIX
from the Marketplace and verify setup, capture, reports, Task Storage, and Task
Transfer without installing the native app.

For optional native-preview acceptance:

1. Download the platform artifact and verify it against `SHA256SUMS.txt` and
   `preview-integrity.json`.
2. Confirm the expected Gatekeeper or SmartScreen warning identifies the build
   as unsigned, then use the platform's deliberate local override.
3. Complete onboarding with background capture both disabled and enabled.
4. Close the app and prove only opted-in background capture remains running.
5. Use **Unregister Background Agent** and **Reset Local Data** and confirm each
   affects only Codex Usage-owned state.
6. On Windows, uninstall with preservation selected, then repeat with local-data
   removal and verify each choice affects only Codex Usage-owned state.

On both platforms, verify ledger-only range/project/theme changes open zero
JSONLs, an unchanged capture reads zero source bytes, Capture Now coalesces,
partial baseline totals remain visibly incomplete, Task Storage analysis is
selected-tree-only and cancellable, and Task Transfer preserves its guarded
one-project contract.
