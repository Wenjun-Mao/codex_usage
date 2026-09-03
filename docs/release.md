# Native Release Checklist

Version 2.0 publishes a native macOS Apple Silicon app, a native Windows x64
app, signed updater bundles, checksums, and one universal optional VS Code
companion. Linux, Intel macOS, and Windows ARM64 are not release targets.

There is **no unsigned release fallback**. Missing Apple, Azure, or Tauri
signing material blocks publication.

## Required Identities And Secrets

### Tauri updater

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

The corresponding public key is committed in
`apps/desktop/src-tauri/tauri.conf.json`. Retain the private key independently;
losing it prevents existing installations from trusting future updates.

### macOS Developer ID and notarization

- `APPLE_CERTIFICATE`: base64-encoded Developer ID Application `.p12`.
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_SIGNING_IDENTITY`
- `APPLE_ID`
- `APPLE_PASSWORD`: app-specific password.
- `APPLE_TEAM_ID`

The Apple account must support Developer ID distribution and notarization. The
workflow imports the certificate into a temporary keychain, signs the app and
sidecar, notarizes/staples the DMG, validates Gatekeeper, and deletes the
temporary keychain.

### Windows Azure Artifact Signing

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `ARTIFACT_SIGNING_ENDPOINT`
- `ARTIFACT_SIGNING_ACCOUNT`
- `ARTIFACT_SIGNING_PROFILE`

Configure a GitHub OIDC federated credential for the repository and grant its
service principal **Artifact Signing Certificate Profile Signer**. Microsoft
requires completed identity validation and an eligible paid, non-sponsored
Azure subscription.

The Windows job signs the application and PyInstaller agent, creates the
per-user NSIS installer, signs that installer, then rebuilds and signs the Tauri
updater archive from the signed installer. Reordering those steps invalidates
the updater signature.

### VS Code Marketplace

- `VSCE_PAT` with Manage permission for publisher `wenjun-mao`.

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

Companion:

```bash
cd extensions/vscode
npm ci
npm test
npm run package:vsix
```

The companion package audit must show no Python, agent executable, parser,
cache, source, or test files.

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

Require all four jobs to pass before publication:

- core/release-contract validation;
- universal VS Code companion packaging;
- macOS ARM64 PyInstaller, frontend, Rust, and no-bundle native smoke;
- Windows x64 PyInstaller, frontend, Rust, and no-bundle native smoke.

This gate intentionally does not produce distributable unsigned installers.

## Signed Publication

Confirm all Python, npm, Cargo, Tauri, and lockfile versions are `2.0.0`, both
changelogs have a dated `2.0.0` entry, and the candidate commit is contained in
`origin/main`.

The only valid release tag for this version is `v2.0.0`. Create and push that
exact tag:

```bash
git tag v2.0.0
git push origin v2.0.0
```

The tag starts the signed path. It must produce these release assets:

```text
Codex-Usage-2.0.0-macos-arm64.dmg
Codex-Usage-2.0.0-darwin-aarch64.app.tar.gz
Codex-Usage-2.0.0-darwin-aarch64.app.tar.gz.sig
Codex-Usage-2.0.0-windows-x64-setup.exe
Codex-Usage-2.0.0-windows-x86_64.nsis.zip
Codex-Usage-2.0.0-windows-x86_64.nsis.zip.sig
codex-usage-companion.vsix
latest.json
SHA256SUMS.txt
```

The workflow verifies native signatures, updater signatures, checksums, all nine
GitHub assets, and Marketplace version availability. Publication is rerunnable:
an existing GitHub release is updated with `--clobber`, and VSCE uses
`--skip-duplicate`.

## Clean-Install Acceptance

On a clean macOS Apple Silicon account:

1. Validate the DMG staple and Gatekeeper assessment.
2. Install and open the app without bypassing security prompts.
3. Complete onboarding with background capture both disabled and enabled.
4. Close the app and prove only opted-in background capture remains running.
5. Install an update from a test endpoint and prove the collector is quiesced,
   registration is repaired, and the app restarts.
6. Use **Unregister Background Agent** and **Reset Local Data** and confirm each
   affects only Codex Usage-owned state.

On a clean Windows x64 account:

1. Verify Authenticode on the installer, app executable, and agent executable.
2. Install per-user without elevation and complete onboarding.
3. Confirm the Scheduled Task appears only after consent and survives app exit.
4. Exercise signed update installation and repaired task registration.
5. Uninstall and choose the default **No** response; verify ledger/settings are
   preserved and the Scheduled Task is removed.
6. Reinstall, uninstall again, choose **Yes**, and verify only Codex Usage-owned
   ledger/settings are removed.

On both platforms, verify ledger-only range/project/theme changes open zero
JSONLs, an unchanged capture reads zero source bytes, Capture Now coalesces,
partial baseline totals remain visibly incomplete, Task Storage analysis is
selected-tree-only and cancellable, and Task Transfer preserves its guarded
one-project contract.
