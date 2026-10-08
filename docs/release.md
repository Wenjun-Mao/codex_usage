# 2.11.0 VSIX Release Checklist

Codex Usage 2.11.0 ships only the macOS Apple Silicon and Windows x64 VS Code
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

## Observed Output Speed Acceptance

Implementation candidate `acc0ee56940327b689f7ba0a082fee8034ef5526` was independently
accepted after exact nonpublishing [platform CI](https://github.com/Wenjun-Mao/codex_usage/actions/runs/37856763085).
ADR 0053 defines the metric and guarded evidence contract. Preserve the accepted
product behavior while preparing release metadata and synthetic images.

Verify additive ledger schema 5 to 6 and parser cache 10 to 11 migrations before
any fallback drop. Speed-only recovery must preserve language events, monetary
revisions, image metadata and repository attribution. Known large media rows
resume within strict byte budgets; generated messages use complete bounded
structural projection, not a truncated content prefix. Ambiguous tool evidence
is scoped to attributable turns or intervals, including execution-capable
Extension items. Conflicting response identities exclude all copies.

Check model-level medians/IQR and range/project filtering, five-response display
gates, 500 output-token floor, Daily/Hourly windows and DST offsets. Capture
retains chart state. Explicit All Projects must include future projects, unlike
a fixed selected subset. Usage has no reload icon; Storage and palette reload
remain available. Warm HTML performs no historical or monetary recomputation.

The actual script-disabled isolated VS Code gate exercised five rendered mouse
clicks and capture-state retention. Its accepted harness source SHA-256 is
`74e083f194d1ae825c17401d0a7058d91e3db61959bb512720092bb1dffa0be9`;
the explicit iframe-target helper is
`5eae5a83f5857cd4fbfff8ee395dae62c1a26bf1b067e0e4b4706ca677148067`.
No retry is needed for metadata-only release changes. Any future disposable host
must retain `--use-inmemory-secretstorage`: temporary HOME alone does not prevent
Electron's native credential storage. Never alter the user's Keychain or profile.

Private captured-data evidence remains ignored, unpublished and bounded to a
hash-matched selected cohort, with identical accepted and display-eligible
observations across whole-object, full, append and recovery paths. The
content-free replay only tests pairing/threshold sensitivity; it is
not production ingestion coverage. These observations do not prove universal
format coverage, server decode speed or a rollout's causal gain. Public fixtures,
screenshots and CI contain synthetic evidence only.

## Included Auto-review Regression Checks

Use the conservative announcement boundary in ADR 0052, not a backdated free
rate. Dedicated `codex-auto-review` events at or after that boundary have zero
estimated Standard credits, remain API-excluded without a public USD rate, and
contribute no unknown-cost tokens to allowance calibration or calibrated pace.
Retain all tokens and source events; ordinary model-based reviews, earlier
unknown prices and unknown review variants must remain unchanged. Check full
and indexed parity, pace arithmetic, and invalidation of old derived costs.

The accepted Share-column cleanup is also included. The separate private MCP
adapter and its sharing-disabled setup are not Marketplace products, and this
VSIX release must not configure a tunnel, enable sharing or expose credentials.

## Credit Balance Regression Checks

Verify the balance shares the Plan Allowance heading without a new standing
paragraph, including at 360 px. Capture exact decimals with the existing RPC;
show missing or conflicting metadata as unknown, stale balances as last known,
and unlimited balances explicitly. Keep history and net changes folded, separate
from token-based credit estimates and banked resets. A reset must not clear credit
history, and increases must not be reported as spending.

Verify a packaged collector migrates a disposable schema-4 ledger through schema 5
to schema 6, preserves events and quota evidence, and leaves a readable
pre-migration backup.
Allowance fits stop before the first raw full-meter reading, including conflicting
same-timestamp evidence and later small corrections. Keep raw observations,
ordinary costs and genuine reset boundaries unchanged. Historical
estimates may change when saturated evidence is excluded. Credit history begins
prospectively; exact billing attribution and credit-depletion pace are not shipped.

## Pace Limits

Recent, Daily and Cycle average rows prefer captured language API-equivalent
cost divided by a compatible full-allowance reference and actual observed hours.
Prefer the usable current-cycle value; otherwise use the latest compatible
previous value, including Low/provisional. Check flat meters with positive cost,
reference switching across all three rows, causal plan/limit/duration identity,
future-reference rejection, true zero cost, and unpriced/incomplete fallback.

Cycle uses the entire observed coherent suffix, including idle time, not an
inferred reset origin. Recent covers up to one hour; Daily up to 24 hours.
Daily's direct-meter fallback also uses plain signed net movement divided by
elapsed hours, with the existing meter evidence gates. Preserve exact live
anchoring, reset/plan/conflict rules, raw full-meter cutoff, local reset
comparisons and forecast expiry. Monetary fits, histories, credit/image
accounting, pricing rates and capture scheduling are unchanged.

Check the same three wrapping rows with estimated labels on cost-based results,
actual spans, local today/tomorrow wording, full dates/offsets on hover and
approximate day/hour reset gaps. Keep cost, reference identity/value/dates,
method, interval, coverage and reasons in existing folded diagnostics. Add no
new UI group. Cost-index revision 2 and existing pace arithmetic remain unchanged;
the additive speed migration and timing revision invalidate relevant reports.

The synthetic 10,000-event/52,001-point two-bucket benchmark measured rate and
reference work below 1 ms after shared preparation; cold materialization still
prepares history. Warm HTML hits use compact state with no historical decoding,
cost scans, fitting, repricing, source reads, capture or probes. Run
`uv run python scripts/benchmark_allowance_pace.py` to measure first
materialization, warm views, quota updates and event updates separately.
Counter assertions protect warm behavior; timing is evidence, not a CI gate.

Disposable captured-data checks established arithmetic, full/indexed parity and
exact monetary-output preservation at bounded retrospective origins. Strict
historical accuracy replay additionally needs reconstructible first availability.
The empirical reference is workload-specific and cannot establish complete
account-wide coverage or contractual entitlement. Predictive exhaustion accuracy
and end-to-end VS Code transport latency remain unvalidated. Keep these limits
in release reporting; this release adds no capture mechanism or pricing redesign.

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
uv run python scripts/check_speed_ui.py
```

Canonical images are `docs/marketplace/extension-usage-synthetic.png` and
`docs/marketplace/extension-storage-synthetic.png`. The Day/Night wide/narrow
Usage matrix is retained beside them. Neither screenshots nor fixture data may
contain personal paths, task content, or a local corpus.
The generator also creates reproducible Day/Night observed-speed section images
from the shared public synthetic timing fixture.

## Legacy Handoff Acceptance

The platform workflow runs `scripts/accept_disposable_handoff.js` on fresh
macOS and Windows runners after each collector package is built. It uses a
synthetic Codex home and an inactive OS registration to verify that the real
supervisor keeps its owned collector, removes the known registration, and
captures into the same ledger. This gate fails if the runner cannot inspect
the OS service registry; it must not silently skip the handoff.

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

Review the candidate diff and local gates before pushing `main`. Then dispatch
the non-publishing workflow from the exact candidate commit on `main` before
tagging:

```bash
gh workflow run package-vsix.yml --ref main -f publish=false
```

Require the `validate`, `macos-vsix`, and `windows-vsix` jobs to pass. Preserve
the run URL and both artifact checksums as release evidence. The macOS job also
checks the extension screenshot and allowance visual gates. A platform gate that
cannot be run is a release blocker, not an implicit pass.

## Marketplace Publication

Confirm Python and extension metadata and lockfiles all say `2.11.0`, both
changelogs contain a dated entry, and the candidate commit is in `origin/main`.
Only after the non-publishing platform gate succeeds, create and push `v2.11.0`:

```bash
git tag v2.11.0
git push origin v2.11.0
```

The tag reruns all platform gates and publishes
`codex-usage-companion-darwin-arm64.vsix` and
`codex-usage-companion-win32-x64.vsix`. Record the tag commit, workflow URL,
Marketplace versions, and package hashes. The workflow does not create a GitHub
Release; VSCE uses `--skip-duplicate` on a rerun.

Query the public Marketplace catalog for version 2.11.0 on both `darwin-arm64`
and `win32-x64`, download each official versioned target VSIX, and require its
SHA-256 to equal the corresponding artifact from the exact tag workflow. Retain
run URLs, catalog metadata and public hashes under ignored release evidence;
the pre-tag build's checksums need not equal the tag rebuild's ZIP bytes.

Tell users with an older native preview to complete explicit service handoff
before uninstalling it, and to preserve their shared `.codex-usage` data.
