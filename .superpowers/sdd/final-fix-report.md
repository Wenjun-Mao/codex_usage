# Final Fix Report

Date: 2026-07-23

Status: COMPLETE

Branch: `codex/deterministic-import-registration`

Implementation commit:
`eda93c78087f9e425fb763b8e68707bad8cc1502`

No release version was changed.

## Finding 1: Registration Certification

### Root cause

The extension treated any non-completed result with a non-empty `pulled`
array as registration evidence. The native result parser established field
shapes, but the registration boundary did not certify the semantic
relationship between `outcome`, `counts.pulled`, `pulled`, and the user's
selected IDs. That allowed conflict results and unselected, duplicate,
noncanonical, or count-inconsistent IDs to reach Codex registration.

The fix belongs at the registration trust boundary because this is the last
point before `thread/read` is invoked. Parser shape validation alone cannot
prove that a task was selected and successfully imported.

### Fix and guardrails

- Registration now accepts all selected IDs only for `completed`.
- An `issue` result is accepted only when its complete pulled set is
  canonical, unique, count-consistent, and contained in
  `selectedThreadIds`.
- `conflict`, unknown outcomes, and any malformed pulled set reject the
  entire registration result.
- Regressions cover conflict-with-pulled, unselected pulled IDs, padded IDs,
  duplicates, count mismatches, and the controller's no-registration path.
- ADR 0016 records the certification and cleanup contracts.

### TDD evidence

RED: the focused registration suite reported 3 failures, demonstrating that
conflict and unselected pulled IDs flowed through to registration.

GREEN:

```text
node --test test/taskTransferRegistration.test.js
9 passed, 0 failed
```

## Finding 2: True Read-Only Scope Validation

### Root cause

`RemoteStore.load_inventory()` combined inventory discovery with mutable
store preparation: it acquired a lock and migrated v2 stores. The
directional preflight and Review paths called that API before validating
one-project scope. Separately, the CLI's local load path could create the
sessions directory and usage cache before scope rejection.

The defect was therefore an inventory contract problem, not a planner
problem. A downstream rollback or cleanup would still violate the
read-only-before-validation guarantee.

### Fix and guardrails

- Added a read-only remote inventory probe for v2 and v3 stores.
- Shared parsing and v2 validation between the probe and migration paths.
- Import and Export now validate scope from read-only probes before a lock,
  migration, transaction, destination write, sessions-directory creation,
  or cache write.
- Directional execution re-probes inside the transaction before
  materializing a validated v2 store.
- Review uses the read-only status plan and never locks or migrates a v2
  store.
- Added a read-only local JSONL session probe so CLI preflight does not
  create or update the usage cache.
- Regressions compare missing parent trees and v2 stores byte-for-byte and
  explicitly assert that no lock appears.
- ADR 0017 records the read-only probe and materialization boundary.

### TDD evidence

RED: the initial focused run reported 8 failures. It exposed lock creation,
v2 migration, local sessions/cache creation, and the unresolved-ID gap.
After the first implementation pass, the only remaining failure showed that
the CLI usage cache was still being created; that evidence led to the local
session probe rather than a cleanup workaround.

GREEN:

```text
focused scope/no-mutation regressions
12 passed

focused Python Task Transfer suite
140 passed
```

## Finding 3: Bounded Process-Tree Cleanup

### Root cause

The app-server session resolved immediately after sending one termination
signal. It did not wait for `close`, enforce a cleanup deadline, or terminate
descendants. Listener removal also allowed process lifecycle events to race
with settlement.

The fix belongs in the process lifecycle owner. Callers cannot reliably
repair an already-resolved child process or discover its descendants.

### Fix and guardrails

- Added a monotonic `cleaning` lifecycle phase before `settled`.
- Cleanup ends stdin, sends graceful termination, and awaits bounded close.
- POSIX candidates run in their own process group; cleanup escalates the
  group from `SIGTERM` to `SIGKILL` and polls for group exit.
- Windows cleanup uses bounded `taskkill.exe /PID <pid> /T /F`.
- Settlement remains single-shot while timers and listeners are detached in
  a controlled order.
- A real Node app-server fixture spawns a descendant; both ignore `SIGTERM`.
  The regression proves the API does not return until neither PID survives.

### TDD evidence

RED: the real-process regression failed because the parent process remained
alive after the session returned.

GREEN:

```text
real forced-cleanup regression
1 passed

app-server focused suites
22 passed, 0 failed
```

## Finding 4: Complete Project Scope

### Root cause

Project-scope resolution built its project set only from selected IDs found
in either inventory. IDs absent from both inventories were silently omitted,
so a mixed known/unknown selection could transfer the known task.

This is a domain-contract gap in scope resolution: every selected ID must be
accounted for before the unique project key can be certified.

### Fix and guardrails

- Scope resolution returns `unresolved_selected_task` as soon as any
  selected ID is absent from both inventories.
- The unresolved check runs before unique-project and declared-project
  checks.
- Core and runner/CLI regressions cover mixed known/unknown selections and
  prove that the transfer tree is unchanged.

The RED/GREEN evidence is included with Finding 2 because the same
preflight/no-mutation test wave exercises both contracts.

## Finding 5: Strict Source-Size Guard

### Root cause

The extension had a changed-file size guard, but Python did not. Three test
modules accumulated unrelated responsibilities and reached 582, 691, and
exactly 500 lines, so the plan's strict under-500 contract was not
executable for Python.

### Fix and guardrails

- Split CLI inventory tests, existing-counterpart security tests, and runner
  timing tests into responsibility-specific modules without dropping tests.
- Added `tests/test_python_source_size.py`, which checks changed Python files
  against the merge base, includes untracked Python files, and preserves a
  bounded fallback for environments without merge-base metadata.
- The existing extension source-size test continues to guard TypeScript and
  JavaScript.

### TDD evidence

RED:

```text
582 tests/test_sync_cli.py
691 tests/test_sync_project_resolution_security.py
500 tests/test_sync_runner_validation.py
```

GREEN:

```text
focused split and Python size-guard suite
46 passed
```

## Changed Files

Architecture and contracts:

- `docs/adr/0016-register-imported-tasks-through-codex.md`
- `docs/adr/0017-one-project-per-transfer-operation.md`

Extension runtime and tests:

- `extensions/vscode/src/codexAppServer.ts`
- `extensions/vscode/src/codexAppServerSession.ts`
- `extensions/vscode/src/codexProcessCleanup.ts`
- `extensions/vscode/src/taskTransferRegistration.ts`
- `extensions/vscode/test/codexAppServer.test.js`
- `extensions/vscode/test/codexAppServerHarness.js`
- `extensions/vscode/test/codexAppServerProcessCleanup.test.js`
- `extensions/vscode/test/taskTransferRegistration.test.js`

Python runtime:

- `src/codex_usage/cli.py`
- `src/codex_usage/sync/directional_preflight.py`
- `src/codex_usage/sync/format_migration.py`
- `src/codex_usage/sync/local_session_probe.py`
- `src/codex_usage/sync/project_scope.py`
- `src/codex_usage/sync/remote_inventory_probe.py`
- `src/codex_usage/sync/runner.py`
- `src/codex_usage/sync/selection_inventory.py`
- `src/codex_usage/sync/store.py`
- `src/codex_usage/sync_cli.py`

Python tests:

- `tests/test_python_source_size.py`
- `tests/test_sync_cli.py`
- `tests/test_sync_cli_inventory.py`
- `tests/test_sync_existing_counterpart_security.py`
- `tests/test_sync_project_resolution_security.py`
- `tests/test_sync_project_scope.py`
- `tests/test_sync_runner_timing.py`
- `tests/test_sync_runner_validation.py`
- `tests/test_sync_scope_read_only.py`
- `tests/test_sync_selection_inventory_loading.py`

## Full Verification

```text
$ uv run pytest -q
595 passed, 1 skipped in 5.84s

$ uv run pytest -q -rs
SKIPPED [1] tests/test_sync_store.py:1746: native junctions are Windows-only
595 passed, 1 skipped in 5.86s
```

```text
$ npm test
tests 224
pass 224
fail 0
cancelled 0
skipped 0
todo 0
duration_ms 162.06025
```

```text
$ npm run test:registration-smoke
Codex registration smoke passed:
registered=packaged-task-a,packaged-task-b
```

```text
$ npm run package:vsix:mac
Packaged Task Transfer smoke passed:
inventory=local,remote pushed=1 pulled=1 status=up-to-date format_version=3
DONE Packaged:
../../output/releases/codex-usage-dashboard-darwin-arm64.vsix
(35 files, 14.47 MB)
```

```text
$ git diff --check
<no output; exit 0>
```

## Changed Source/Test Line Counts

```text
123 extensions/vscode/src/codexAppServer.ts
406 extensions/vscode/src/codexAppServerSession.ts
42 extensions/vscode/src/taskTransferRegistration.ts
216 extensions/vscode/src/codexProcessCleanup.ts
288 extensions/vscode/test/codexAppServer.test.js
165 extensions/vscode/test/codexAppServerHarness.js
289 extensions/vscode/test/taskTransferRegistration.test.js
128 extensions/vscode/test/codexAppServerProcessCleanup.test.js
423 src/codex_usage/cli.py
111 src/codex_usage/sync/directional_preflight.py
362 src/codex_usage/sync/format_migration.py
80 src/codex_usage/sync/project_scope.py
487 src/codex_usage/sync/runner.py
275 src/codex_usage/sync/selection_inventory.py
415 src/codex_usage/sync/store.py
328 src/codex_usage/sync_cli.py
126 src/codex_usage/sync/local_session_probe.py
210 src/codex_usage/sync/remote_inventory_probe.py
479 tests/test_sync_cli.py
403 tests/test_sync_project_resolution_security.py
166 tests/test_sync_project_scope.py
466 tests/test_sync_runner_validation.py
405 tests/test_sync_selection_inventory_loading.py
94 tests/test_python_source_size.py
157 tests/test_sync_cli_inventory.py
374 tests/test_sync_existing_counterpart_security.py
105 tests/test_sync_runner_timing.py
271 tests/test_sync_scope_read_only.py
```

Maximum: 487 lines. Every changed Python, TypeScript, and JavaScript
source/test file is strictly under 500 lines.

## Commit and Clean Status

```text
eda93c78087f9e425fb763b8e68707bad8cc1502
fix: close final task transfer review gaps
```

After the implementation commit:

```text
$ git status --short
<no output; clean>
```

This report is committed separately so it can cite the immutable
implementation commit. Its commit hash and the final clean-status check are
reported in the final task response.

## Remaining Concerns

- The real stubborn process-tree regression ran on macOS/POSIX. The Windows
  `taskkill /T /F` escalation path is implemented and type/test/package
  covered, but a real Windows process-tree run was not available here.
- The one skipped Python test exercises native Windows junctions and is
  expected to skip on macOS.
