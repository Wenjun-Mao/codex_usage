# 2.9.1 VSIX Release Checklist

Codex Usage 2.9.1 ships only the macOS Apple Silicon and Windows x64 VS Code
Companion packages. Each VSIX contains exactly one matching, bundled Python
collector. The extension does not require the former Tauri app, Python, `uv`,
or a source checkout on the user's machine.

## Release Contract

- Preserve the existing `CODEX_HOME/.codex-usage/usage-ledger.sqlite3`, settings,
  source events, and Task Transfer data. Do not test handoff against live data.
- Scheduled capture runs while VS Code is open, even with the dashboard closed.
  The parent-bound collector exits when the final extension host closes. Missed
  quota snapshots during downtime may be impossible to reconstruct.
- A legacy registered Codex Usage LaunchAgent or Windows Scheduled Task remains
  untouched until the user runs **Codex Usage: Retire Legacy Background Service**
  and confirms. Handoff removes only the known service, waits for any old
  background writer to exit, and starts or keeps the bundled collector on the
  same home and ledger. A refusal leaves the service in place. A failure must
  be visible and recoverable without **Reset Local Data**. An inactive legacy
  registration can be retired while VS Code keeps its
  already owned collector. An unrecognized command or ambiguous macOS launchd
  state leaves the registration in place. Handoff verifies the selected home,
  ledger revision, and first capture outcome before reporting success.
- Both platform VSIX jobs must pass before publication. No DMG, NSIS, Tauri,
  Cargo, signing, or native-preview artifact is part of this release.

`VSCE_PAT` with Manage permission for publisher `wenjun-mao` is the sole
publication secret.

## Local Gates

From the repository root:

```bash
uv sync --all-groups
uv run pytest -q
uv run ruff check .
```

From `extensions/vscode`:

```bash
npm ci
npm test
npm run package:vsix:mac  # macOS Apple Silicon
# npm run package:vsix:win  # Windows x64
```

The package command builds and smoke-tests the PyInstaller collector, then
checks the extension payload. Audit the produced archive as well:

```bash
uv run python scripts/verify-vsix-archive.py output/releases/codex-usage-companion-darwin-arm64.vsix darwin-arm64
# On Windows, use the win32-x64 artifact and target.
```

The archive must contain the matching executable, `extension/package.json`, and
`extension/out/extension.js`, with no second collector or Tauri files. Confirm a
clean VSIX install can choose `CODEX_HOME`, capture, render Usage and Task
Storage, export Agent Activity, and perform Task Transfer without former native
app files.

## Visual Gate

The screenshot generator renders the production extension webview HTML with
synthetic, privacy-safe data. Inspect Day and Night at wide and narrow sizes,
plus the Task Storage image. Check controls, disclosures, keyboard access,
allowance semantics, tooltips, labels, and clipping. Regenerate and verify:

Visually review Usage at 1440 x 900 and 760 x 900 in both themes. Verify the
Task Storage surface, Task Transfer stages, contextual reload controls, range
and project filters, capture state, Model Details, Plan Allowance diagnostics,
and export affordances stay readable and operable. Record any browser-specific
meter or clipping difference before promotion.

```bash
uv run playwright install chromium firefox webkit
uv run python scripts/generate_marketplace_screenshot.py
uv run python scripts/generate_marketplace_screenshot.py --check
uv run python scripts/check_allowance_ui.py
```

Canonical images are `docs/marketplace/extension-usage-synthetic.png` and
`docs/marketplace/extension-storage-synthetic.png`. The Day/Night wide/narrow
Usage matrix is retained beside them. Neither screenshots nor fixture data may
contain personal paths, task content, or a local corpus.

## Legacy Handoff Acceptance

Use a disposable `CODEX_HOME` and disposable known-service registration on
macOS and Windows. Record before/after ledger revision, event count, settings,
and selected home. Verify refusal leaves registration and writer unchanged;
confirmation removes only the known registration, waits for the prior writer,
and yields one VS Code-owned writer. Capture again and verify the same ledger
advances without duplicate events. Test a missing legacy executable, failed
unregistration, an inactive service with an already owned VS Code collector,
foreign transient ownership, lookalike service commands, ambiguous launchd
status, a mismatched home, failed capture, and recovery instructions. Never
unregister a live service or modify a live ledger for release testing.

Also verify scheduled capture while the webview is closed, clean shutdown when
the last extension host exits, and resumed capture against the same ledger on
reopen. The report should mark quota observation gaps rather than imply
continuous coverage.

## Non-Publishing Platform Gate

Push the candidate branch and dispatch the workflow from that branch before
review. For the 2.9.1 patch candidate:

```bash
gh workflow run package-vsix.yml --ref codex/2.9.0-extension-only -f publish=false
```

After an approved candidate is merged, dispatch again from `main` before
tagging:

```bash
gh workflow run package-vsix.yml --ref main -f publish=false
```

Require the `validate`, `macos-vsix`, and `windows-vsix` jobs to pass. Preserve
the run URL and both artifact checksums as release evidence. The macOS job also
checks the extension screenshot and allowance visual gates. A platform gate that
cannot be run is a release blocker, not an implicit pass.

## Marketplace Publication

Confirm Python and extension metadata and lockfiles all say `2.9.1`, both
changelogs contain a dated entry, and the candidate commit is in `origin/main`.
Only after the non-publishing platform gate succeeds, create and push `v2.9.1`:

```bash
git tag v2.9.1
git push origin v2.9.1
```

The tag reruns all platform gates and publishes
`codex-usage-companion-darwin-arm64.vsix` and
`codex-usage-companion-win32-x64.vsix`. Record the tag commit, workflow URL,
Marketplace versions, and package hashes. The workflow does not create a GitHub
Release; VSCE uses `--skip-duplicate` on a rerun.

Tell users with an older native preview to complete explicit service handoff
before uninstalling it, and to preserve their shared `.codex-usage` data.
