# Developer Exercises

These exercises are meant to build skill from this specific project.

## 1. Trace One Token Event

Pick a tiny synthetic JSONL fixture. Trace one `token_count` event through:

1. `parser.py`
2. `UsageRecord`
3. `session_cache.py`
4. `aggregation.py`
5. `pricing.py`
6. `report_view.py`
7. `reporting.py`

Write down where cumulative totals become deltas.

## 2. Add A Synthetic Price Change

Add a test-only rate change for a fake model. Create two usage records on opposite sides of the effective date. Verify the same summary uses different rates for each record.

Lesson: historical pricing belongs at the record timestamp, not the report timestamp.

## 3. Write A Parser Regression Fixture

Create a minimal JSONL fixture where:

- one line is malformed;
- one token event has null info;
- two token events repeat the same cumulative total;
- one later token event increases output tokens.

Expected result: only the positive increase becomes usage.

## 4. Explain Project Identity

Use one example where `git.repository_url` exists and one where only `cwd` exists. Explain:

- how the project key is chosen;
- what aliases are kept;
- why labels are not used as identity.

## 5. Inspect A VSIX

Build and inspect:

```powershell
cd <repo-root>\extensions\vscode
npm run package:vsix:win
cd ..\..
tar -tf output\codex-usage-dashboard-win32-x64.vsix
```

Confirm the package includes compiled output and the bundled executable, not TypeScript source.

## 6. Diagram Sync State

Draw the base/local/remote cases for:

- first push;
- first pull;
- already synced;
- local fast-forward;
- remote fast-forward;
- divergent conflict.

Then compare your diagram to `sync status --json`.

## 7. Write A Linux Runtime ADR

Pretend the next release supports Linux x64. Write an ADR that chooses between:

- bundle a Linux executable;
- require Python/uv;
- ship a TypeScript-only port;
- run through a background service.

The ADR should state the user impact, packaging impact, and test plan.
