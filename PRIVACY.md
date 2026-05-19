# Privacy

Codex Usage Dashboard is designed as a local-first tool.

## What It Reads

- Local Codex session JSONL files from the detected Codex sessions directory.
- Optional user-provided settings such as `codexUsage.sessionsDir`, `codexUsage.range`, `codexUsage.projectKeys`, and `codexUsage.subscriptionUsd`.

## What It Writes

- Local HTML reports under VS Code extension storage.
- Optional local CLI outputs such as JSON, CSV, and HTML reports when you run `codex-usage` directly.

## Network And Telemetry

- The extension does not upload Codex session logs.
- The extension does not include telemetry.
- The extension does not fetch live pricing data.
- API-equivalent USD and Codex credit estimates use checked-in effective-dated pricing tables.

## Data Sensitivity

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. Do not share raw logs or generated reports unless you are comfortable sharing that metadata.

The screenshot in this repository is synthetic and does not contain real session data.
