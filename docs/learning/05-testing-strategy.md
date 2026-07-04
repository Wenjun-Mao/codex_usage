# Testing Strategy

The tests protect the contracts that would be expensive to rediscover manually.

## Test Pyramid For This Project

Most tests should be unit tests because the core is local and deterministic:

- parser fixtures;
- pricing math;
- aggregation rollups;
- project identity and transition detection;
- cache refresh behavior;
- sync conflict planning;
- TypeScript argument builders and webview helpers.

End-to-end smoke tests still matter for packaging:

- run Python tests;
- run TypeScript tests;
- build the Windows executable;
- package the VSIX;
- smoke the bundled executable.

## Parser Tests

Parser tests are critical because JSONL event shape is the external input contract.

What they protect:

- null `token_count.info` is ignored;
- repeated cumulative records do not double count;
- positive deltas are used;
- model changes inside one session are captured;
- sessions spanning days price and group correctly;
- fork replayed history is not counted as new usage.

Future me: whenever a real Codex log surprises the parser, first make a tiny redacted fixture. Do not debug against a giant raw log forever.

## Pricing Tests

Pricing tests protect money math and rate lookup semantics.

What they protect:

- cached input and uncached input are priced differently;
- output has its own rate;
- API USD and Codex credits are separate;
- `at=None` returns the latest known rate for ad hoc use;
- historical records use rates effective at the event timestamp;
- unknown models remain explicitly unpriced.

## Cache Tests

Cache tests protect performance and historical retention.

What they protect:

- unchanged files are reused;
- changed files are reparsed;
- failed parses do not wipe previous good cache rows;
- deleted or missing files can remain in historical totals after being parsed;
- archived session files remain included;
- schema rebuilds preserve compatible retained history.

This is why cache is not just "speed." It is also the layer that makes archive/delete behavior less surprising.

## Sync Tests

Sync tests protect user data.

What they protect:

- export copies only selected conversations;
- import backs up before overwrite;
- index entries merge by newest update;
- unsafe thread ids are stored under filesystem-safe names;
- local-only and remote-only states plan push/pull;
- prefix fast-forward is allowed;
- divergent non-prefix changes become conflicts.

Sync should be conservative by default. A false conflict is annoying. A silent overwrite is much worse.

## TypeScript Tests

Extension tests protect the thin wrapper contract:

- command argument arrays do not use shell strings;
- webview HTML remains script-free and CSP-restricted;
- global state values normalize safely;
- QuickPick parsers handle CLI JSON;
- status bar labels are concise;
- Marketplace metadata stays publishable.

Future me: test the pure functions in `core.ts`. Keep VS Code API calls in `extension.ts` thin enough that manual smoke tests can cover them.

## Verification Commands

Use these before release-like changes:

```powershell
uv run pytest
cd extensions\vscode
npm test
npm run package:vsix:win
```

On macOS Apple Silicon:

```bash
cd extensions/vscode
npm test
npm run package:vsix:mac
```

For bundled runtime smoke:

```powershell
cd <repo-root>
.\extensions\vscode\bin\win32-x64\codex-usage.exe report --range 7d --theme night --output output\smoke.html
```
