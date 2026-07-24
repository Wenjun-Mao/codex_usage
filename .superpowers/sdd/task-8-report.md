# Task 8 Report: Packaged Codex Registration Gate

## Files

- Added `scripts/fake-codex-app-server` and `scripts/smoke-test-codex-registration.js`.
- Updated the packaged Python smoke, its validation constants, and focused smoke tests.
- Added `test:registration-smoke`, native release workflow gates, and core workflow/argv assertions.

## TDD Evidence

- RED: the registration gate test failed because the real-process smoke script was absent; the packaged smoke test failed because transfer commands omitted `--project-key`.
- RED: the fixture initially failed under Node 24 because CommonJS `require` and top-level `await` made the extensionless script ambiguous. Wrapping the loop in `main()` fixed the module contract.
- RED: native packaging revealed that the unrelated task inflated the initial inventory and that a valid `cross_project_selection` response exits with code `2`. Tests now require delayed fixture creation and explicitly permit code `2` only for this expected issue assertion.
- GREEN: the registration smoke registers two ids through `process.execPath app-server --stdio`; the packaged Python smoke verifies the blocked cross-project selection and unchanged local/remote task files.

## Verification

- `npm test`: 220 passed.
- `npm run test:registration-smoke`: passed; registered `packaged-task-a,packaged-task-b`.
- `uv run pytest tests/test_packaged_sync_smoke.py -q`: 40 passed.
- `npm run package:vsix:mac`: passed; packaged smoke reported `inventory=local,remote pushed=1 pulled=1 status=up-to-date format_version=3` and created `output/releases/codex-usage-dashboard-darwin-arm64.vsix`.

## Commit

- `test: gate packaged Codex task registration` (this task commit).

## Concerns

- None. The CI workflow will execute the platform-neutral registration smoke on both Windows x64 and macOS Apple Silicon before VSIX packaging.

## Review Follow-Up

- P1 now snapshots every file beneath the operation's remote `tasks/` directory as relative paths and bytes before the rejected cross-project transfer, then compares the full mapping afterward. The focused regression injects `tasks/unrelated-thread.jsonl` and requires the smoke to fail.
- P2 now independently requires nonnegative `npm ci`, registration-smoke, and package indices for each native job, and asserts `install < smoke < package`.

### Commands And Results

- `uv run pytest tests/test_packaged_sync_smoke.py::test_rejected_cross_project_extra_remote_task_write_fails_native_smoke tests/test_packaged_sync_smoke.py::test_packaged_sync_smoke_orchestrates_exact_round_trip -q`: 2 passed.
- `node --test --test-name-pattern='native release jobs gate direct Codex registration' test/core.test.js`: 1 passed.
- `npm test`: 220 passed.
- `npm run test:registration-smoke`: passed; registered `packaged-task-a,packaged-task-b`.
- `uv run pytest tests/test_packaged_sync_smoke.py -q`: 41 passed.
- `npm run package:vsix:mac`: passed; packaged task-transfer smoke passed and produced `output/releases/codex-usage-dashboard-darwin-arm64.vsix`.
