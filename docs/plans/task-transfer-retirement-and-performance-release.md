# Task Transfer Retirement And Performance Release

Date: 2026-10-22, America/Toronto.
Status: implementation and 2.13.0 release approved by the owner on 2026-10-22
via Relay direct. Local implementation in progress; not yet qualified/published.

Execution checkpoint: candidate `f5800d1a` passed complete product checks and
both hosted package/visual matrices, but its normal qualification failed at
core receipt generation on a randomized required pytest identity. The fixed
fixture and strict local-inventory command pass 2,903 local cases and exact
inventory validation. The failed run is retained; a fresh hosted run requires
the separately requested owner approval. No tag or publication has occurred.

## Outcome

Retire Task Transfer completely as a supported product feature and release the
already implemented dashboard preparation improvements together with that
retirement. Version: **2.13.0**, confirmed unused during candidate preparation.
The removal warrants a clearly
announced minor release rather than presenting it as a tooltip-sized patch.

The owner approved retirement in principle, preservation of existing chats and
transfer files, documentation/test updates, and a subsequent combined release.
The owner requested this plan before implementation. Implementation approval
should explicitly carry the execution envelope below; no separate task, Goal,
worktree, automation, installation or live-data repair is part of this plan.

## Authority And Boundaries

- Work serially in the retained checkout. Preserve unrelated `apps/`, submitted
  consultant reports, existing research and all owner changes.
- Existing chats, rollout files, session indexes, Codex databases/global state,
  transfer folders, paired-transfer state and existing exports remain untouched.
  Retirement is code removal, not a filesystem cleanup or data migration.
- Preserve the saved `transfer_folder` value as inert legacy settings data.
  Unrelated settings updates must not erase it. Do not resolve, stat, enumerate,
  migrate or clean the folder merely because an old path remains configured.
- Remove the supported Import, Export and Review Status workflows, including
  hidden entrypoints. Do not retain a new legacy importer or export-only product.
- Keep Usage, capture, Task Storage, Agent Activity CSV, project transitions,
  legacy usage-cache migration and explicit legacy-service handoff operational.
- Do not implement the newly discovered desktop-registration workaround in the
  importer. The owner confirmed the two repaired chats look correct after the
  bounded recovery; retirement does not undo those assignments.
- Do not resume Python 3.15/Rust experiments, redesign test scheduling, change
  tooltip timing policy or continue optimizing until 3s/5s in this release.

Background: [migration investigation](../research/2026-10-22-migrated-chat-project-membership.md),
[existing performance plan](dashboard-preparation-performance.md),
[promotion procedure](../release/qualified-promotion.md).

## Design

The retirement decision is settled. Hiding the toolbar while keeping CLI/API
import paths would retain the same ownership and compatibility burden. Removing
only Import would leave an export format without a supported continuation path.
Neither is the selected design.

Codex owns ongoing chat mobility. Current product guidance should point to
[native host handoff](https://learn.chatgpt.com/docs/remote-connections#hand-off-a-chat-between-hosts),
not reimplement it. Explain that it requires connected hosts and matching saved
Git projects, transfers chat/Git state and can interrupt active work. Do not
claim that it solves offline recovery, dead-machine recovery or arbitrary
non-Git migrations. Existing exported data remains user-owned; there is no
promise that a retired package is a safe importer for future Codex versions.

Use one concise retirement ADR during implementation. Mark the relevant active
Task Transfer decisions as superseded without rewriting historical release
receipts, old changelog entries or original decisions into present-day claims.

## Ordered Deliverables

### 1. Freeze Scope And Contracts

- [x] Inventory tracked and relevant untracked performance/retirement inputs;
  record the current HEAD and preserve unrelated files. Stage only scoped work.
- [x] Write the retirement ADR and map every product entrypoint, shared helper,
  transfer-only test and packaging gate to remove or retain.
- [x] Separate runtime discovery/process cleanup from task registration where
  needed: `allowance_probe.py` and `app_server_rpc.py` currently depend on
  helpers inside `codex_registration.py`. Preserve behavior and helper tests.
- [x] Define removed HTTP routes as ordinary unknown routes, rejected before
  queueing transfer work; removed CLI commands fail argument parsing. Keep the
  surviving API and client-incompatibility/writer-ownership safeguards intact.
- [x] Check dependency consumers before removing any package. Names such as
  `ledger_sync.py` and `ledger_transition_sync.py` are not Task Transfer.

Primary files: `src/codex_usage/agent_transfer.py`, `desktop_binding.py`,
`codex_registration.py`, `app_server_rpc.py`, `allowance_probe.py`, `sync_cli.py`,
`sync/`, `cli.py`, `agent_api.py`, `agent_features.py`, `agent_settings.py`.
Shared helpers may move into a cohesive runtime module, not another catch-all.

### 2. Remove Product And Packaging Paths

- [x] Remove the five transfer commands, activation entry, toolbar link,
  command-link permission, setup-folder choice, transfer client/contract/types,
  manifest keyword and obsolete TypeScript build inputs.
- [x] Remove transfer HTTP dispatch/jobs, CLI handlers and transfer-only engine,
  registration and desktop-binding code after shared-helper extraction.
- [x] Remove transfer-only packaged smoke scripts and their macOS/Windows build
  invocations. Retain collector, report, storage, archive, parallel-worker and
  legacy-service handoff checks.
- [x] Build from cleaned generated output so deleted TypeScript/Python modules
  cannot survive as stale artifacts. Assert that the shipped command inventory
  and executable no longer expose transfer, not merely that the button is gone.

Extension files include `extensions/vscode/package.json`, `tsconfig.json`,
`src/extension.ts`, `reportHtml.ts`, `setupPresentation.ts`, `types.ts`,
`taskTransferClient.ts`, `taskTransferContract.ts` and their tests.
Build files include `scripts/build-macos-arm64-exe.sh`,
`build-windows-exe.ps1`, `smoke-test-packaged-sync.py` and
`packaged_sync_smoke_validation.py` plus actual remaining consumers.

### 3. Replace Coverage And Update Product Documentation

- [x] Add retirement regressions: absent commands, links, setup choices and
  transfer routes; rejected obsolete CLI/API calls; no transfer job or Codex
  registration RPC; preserved unrelated workflows and runtime discovery.
- [x] Use disposable profiles and synthetic transfer folders with content
  hashes/sentinels. Verify startup, settings round trips and relevant remaining
  operations preserve chat/transfer files and legacy transfer bookkeeping.
  Prove that a saved missing, inaccessible or symlinked transfer path is ignored.
  Never inspect or mutate live chat/transfer data to run these tests.
- [x] Remove tests solely exercising deleted behavior. Retain or relocate tests
  of shared helpers and surviving contracts. Replace current documentation
  assertions that require Task Transfer with explicit retirement assertions.
- [x] Review required Python/extension case inventories: record each removed
  case and retirement rationale, add the new guard cases, and preserve every
  unrelated required case. Remove the obsolete transfer-only junction-skip
  allowance if its test is deleted. Do not blanket-regenerate a weaker baseline.
- [x] Add negative verifier tests proving missing surviving cases, incomplete
  inventories and unexpected skips still fail qualification.
- [x] Update both READMEs, support/privacy copy, release instructions and
  screenshots. Include a short removal/data-preservation notice and native
  handoff guidance. Keep historical changelogs/receipts intact; add new entries.

Relevant verification files: `tests/test_task_transfer_docs.py`,
`test_agent_api.py`, `test_agent_settings.py`, transfer-only tests/support,
extension command/setup/report tests, `scripts/generate_marketplace_screenshot.py`,
`scripts/verification/test_inventory.py`, the two case baselines and release
contract tests. Scan active source/docs for dangling paths, not historical
mentions that should remain.

### 4. Qualify The Combined Local Candidate

- [x] Include the existing writer-admission correction and performance work in
  ADRs 0072-0075: snapshot-pinned preparation, incremental history reuse, compact
  capture encoding, batch valuation, ordered turn arithmetic and CSV fixes.
  Do not drop these untracked modules or tests while deleting transfer code.
- [x] Run focused removal/settings/API/helper and release-inventory checks;
  then full Python, extension tests/build, Ruff, lock/version validation, exact
  monetary parity and bounded-work checks for the final candidate.
- [ ] Regenerate/review synthetic Usage/Storage screenshots and run affected
  browser suites across supported engines/themes/viewports. Preserve remaining
  hover, filtering, history, range navigation and CSV assertions.
- [x] Audit a disposable packaged macOS candidate, including upgrade from
  2.12.5-era settings/data, legacy derived-cache formats, corrupted cache recovery,
  capture/report contention, owned collector shutdown and safe incompatibility.
  No normal VS Code installation, live capture or service changes.
- [x] Reuse existing measured evidence to explain each adopted optimization.
  Run one bounded final comparison against published 2.12.5 source on one fresh
  coherent private read-only ledger snapshot, with writes only to disposable
  copies. Use ten alternating unprofiled pairs after an excluded preparation
  pair, following the existing performance plan. Keep at most the frozen input
  and one working database; remove owned private database copies afterward.
- [x] Measure first Today, first 30-day switch, post-append Today/30-day, warm
  navigation, CSV, peak memory and cache/WAL growth. Check exact accounting,
  populations and CSV; allow only reviewed intentional removal/version changes
  in HTML comparisons. Retain samples and report medians/ranges, not p95 from
  ten samples or an inferred universal speedup.

The [final matched 2.12.5 comparison](../research/2026-10-22-2.13.0-candidate-comparison.md)
records ten pairs, exact output checks, source identities, local verification
and the still-unmet targets. Existing earlier local evidence measured first 30 days 8.96 -> 8.06s and
post-append 30 days 7.33 -> 6.72s relative to the preceding optimization pass;
post-append Today was 8.27 -> 8.12s. These are different comparison boundaries
from the user's 22.97s observation and must not be combined into a release claim.
The 3s Today / 5s first-30-day targets remain open follow-up work. Release the
verified gains now, not a claim that those targets are met. Investigate material
regressions before shipping rather than broadening this into another tuning pass.

An independent bounded read-only review is useful once the final diff is stable:
focus on accidental shared-code removal, preservation, cache invalidation and
qualification coverage. Use Relay direct after implementation approval, announce
the actual selected model/effort before dispatch, and review its output locally.
No parallel writers or separate tasks are needed for this plan.

### 5. Prepare And Publish Exact Qualified Packages

- [x] Confirm 2.13.0 is unused; update Python/extension versions, lockfiles,
  both changelogs and the independent release-history expectations. State the
  feature removal and honest measured performance limits.
- [ ] Complete the final local checks/preflight after all source, screenshot,
  metadata and test-inventory changes. Commit only the reviewed scoped changes
  and push the exact retained `main` candidate when execution is authorized.
- [ ] Use the existing coordinator from base `v2.12.5` for one fresh normal
  nonpublishing qualification. Require all surviving core/accounting, visual,
  macOS/Windows package/smoke/archive/handoff and exact-package native macOS
  proof. Retired test cases are not permission to skip unrelated gates.
- [ ] Perform one credential-free dry-run promotion for the selected successful
  run/attempt. Source or qualification-contract changes invalidate prior proof.
  No extra failure/retry or latency pilots are routine requirements here.
- [ ] After qualification/dry-run pass, use the existing explicit promotion
  path: immutable `v2.13.0` at the qualified SHA, exact qualified VSIX bytes,
  retained publication intents and both Marketplace targets. Never rebuild
  packages during promotion or treat a tag as publication authority by itself.
- [ ] Independently verify official versioned downloads/catalog hashes for
  both targets. Preserve pending/partial states without duplicate uploads.
  Review and commit the generated release receipt/status documents, and report
  actual phase timings from the coordinator. Installation remains user-owned.

## Execution Permissions And Stop Conditions

Planning performed no tests, package activation, commits, pushes, hosted runs,
tags, credential access or publication. The owner explicitly approved the
following implementation/release envelope on 2026-10-22:

- Scoped code/docs/test edits and commits, pushes to existing `main`, local
  verification/builds and disposable synthetic browser/package/native checks.
- The already granted private read-only snapshot permission carries forward;
  no raw-log copies, live-ledger writes, account calls or private uploads.
- One normal hosted qualification, one nonpublishing dry-run and one explicit
  production promotion of that exact candidate, with bounded read-only status
  and public-propagation observation using the existing release procedure.
- No automatic workflow reruns, extra diagnostic pilots or replacement
  qualification dispatches. A failure requiring another hosted execution needs
  a new explicit request, consistent with the owner's CI preference.
- No secrets/settings/permission changes, journal rebootstrap/history reset,
  normal extension installation, live service changes, Codex chat operations or
  additional cleanup. Escalate if a gate requires any of these.

Stop before promotion for failed or incomplete proof, an occupied version/tag,
unexplained accounting/data differences or a material regression. Preserve
evidence and diagnose the owning layer; do not relax gates to make the release.
After an ambiguous upload, reconcile retained intents and official hashes; never
infer retry safety from catalog absence. Source fixes require fresh exact proof.

Before publication, revert only owned scoped changes if necessary; preserve
owner work and qualification evidence. After publication, corrections use a new
version, not overwritten tags/packages. Do not recommend downgrading a live
ledger blindly: demonstrate format compatibility on disposable data first, or
prefer a forward fix. Task Transfer retirement itself has no data rollback step
because it must make no chat/transfer-data changes.

## Acceptance Summary

1. No supported or hidden Task Transfer execution path remains in the shipped
   extension/collector, and preserved legacy settings cannot activate one.
2. Synthetic upgrade checks prove no mutation of existing chats, transfer files
   or transfer bookkeeping; no live preservation test touches real data.
3. Usage/capture/storage/CSV/allowance behavior and exact monetary accounting
   remain correct; shared Codex probing/runtime helpers still work.
4. Existing performance optimizations are included, new measurements are honest,
   and unmet 3s/5s targets remain explicitly open rather than delaying retirement
   indefinitely or being declared complete.
5. Current docs/screenshots describe the actual product; historical evidence is
   preserved, and surviving test/gate inventories remain enforced.
6. Both published target packages match one freshly qualified source/run/attempt
   and public hashes, with receipts and release timings. No automatic install.
