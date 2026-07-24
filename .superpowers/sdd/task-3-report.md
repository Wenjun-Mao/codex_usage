# Task 3 Report: Carry and Defend the Project Contract Through the Extension

## Status

Complete. Import and Export now carry one validated picker project through the
controller, protocol builders, and VS Code adapter. Review remains a distinct,
cross-project, keyless request.

## Root Cause

- What failed: the picker returned a project key, but the controller trusted its
  selected task IDs independently and transfer argv omitted the project key.
- Why: the extension request model represented transfer and Review with the same
  keyless shape, and destination resolution rediscovered projects from task IDs.
- Evidence: controller RED tests showed cross-project IDs reached a destination
  prompt, protocol RED tests showed pull/push omitted `--project-key`, and adapter
  RED tests retained generic progress and destination titles.
- Fix layer: validation belongs immediately after picker resolution, before
  prompts or execution; the validated project then becomes the transfer request
  contract. Review uses a separate request because its cross-project behavior is
  intentional. ADR 0017 already records this decision.

## RED Evidence

- `node --test test/taskTransferProjectScope.test.js`: failed because
  `taskTransferProjectScope` did not exist.
- `node --test test/syncProtocol.test.js`: 6 expected failures; pull/push omitted
  the project key, blank keys did not throw, and the transfer option type was
  absent.
- `node --test test/taskTransfer.test.js test/taskTransferProjectResolution.test.js`:
  3 expected failures; execution lacked key/label and a cross-project selection
  reached destination resolution.
- `node --test test/taskTransferVscode.test.js`: 3 expected failures for generic
  import/export progress titles and the old destination title.

## GREEN Evidence

- Scope validator: 6 passed.
- Controller, protocol, scope, and project-resolution tests: 49 passed.
- Adapter tests: 11 passed.
- Brief's exact focused command after build: 56 passed, 0 failed.
- Full `npm test`: 177 passed, 0 failed.
- `git diff --check`: passed.

## Files

Production:

- `extensions/vscode/src/taskTransferProjectScope.ts`
- `extensions/vscode/src/syncCommandArgs.ts`
- `extensions/vscode/src/syncProtocol.ts`
- `extensions/vscode/src/taskTransfer.ts`
- `extensions/vscode/src/taskTransferVscode.ts`

Tests:

- `extensions/vscode/test/taskTransferProjectScope.test.js`
- `extensions/vscode/test/taskTransferProjectResolution.test.js`
- `extensions/vscode/test/syncProtocol.test.js`
- `extensions/vscode/test/taskTransfer.test.js`
- `extensions/vscode/test/taskTransferVscode.test.js`
- `extensions/vscode/test/taskTransferFixtures.js`
- `extensions/vscode/test/taskTransferConcurrency.test.js`
- `extensions/vscode/test/taskTransferNotifications.test.js`

## Self-Review

- Validation filters inventory by operation, requires the picker project, rejects
  foreign IDs, and deduplicates IDs without reordering.
- Import destination resolution consumes one validated project and prompts at
  most once. Cross-project selections fail before prompts and execution.
- Pull/push require one nonblank key; status cannot require or emit one.
- Transfer execution carries the exact project key and label. Review accepts
  task IDs across projects and its request contains neither field.
- Progress titles and destination dialog copy match the brief exactly.
- Focused argument construction keeps `syncProtocol.ts` at 413 lines;
  `taskTransfer.ts` is 450 lines. Every touched TS/test file is below 500 lines.

## Concerns

No known functional concerns.

## Review Fix: Incompatible Review Request Contract

### Status

Review now explicitly forbids the transfer-only `projectKey` and `projectLabel`
fields. A dedicated TypeScript contract test proves an execution request cannot
cross the `TaskTransferPort.review` boundary.

### RED / GREEN Evidence

RED:

`npm run typecheck:contracts`

- Exited 2 with
  `TS2578: Unused '@ts-expect-error' directive`, proving TypeScript accepted
  `reviewBoundary.review(executionRequest)` under the structural base alias.

GREEN:

`npm run typecheck:contracts`

- Exited 0 after `TransferReviewRequest` added `projectKey?: never` and
  `projectLabel?: never`.

Focused Task 3 verification:

- `npm run build`: passed.
- `node --test test/taskTransferProjectScope.test.js test/syncProtocol.test.js test/taskTransfer.test.js test/taskTransferVscode.test.js`:
  56 passed, 0 failed.

Full extension verification:

- `npm test`: type contract check passed; 177 runtime tests passed, 0 failed.
- `git diff --check`: passed.

### Changed Files

- `extensions/vscode/src/taskTransfer.ts`
- `extensions/vscode/test/taskTransferTypeContracts.test.ts`
- `extensions/vscode/tsconfig.type-tests.json`
- `extensions/vscode/package.json`
- `.superpowers/sdd/task-3-report.md`

### Self-Review

- The positive compile-time assertion still accepts a genuine
  `TransferReviewRequest`.
- The negative assertion calls the real `TaskTransferPort.review` boundary and
  fails compilation without the incompatibility; it does not inspect source
  text.
- `npm test` runs the type contract check on every full extension test run.
- Review runtime construction is unchanged, remains cross-project, and the
  status argv regression test still proves no `--project-key` is emitted.
- `taskTransfer.ts` is 453 lines and the type contract test is 14 lines.

### Concerns

No known concerns.
