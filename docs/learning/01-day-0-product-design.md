# Day 0 Product Design

This is how the project should be framed before writing code.

## Problem

Codex stores useful local session data, but the official usage dashboard does not show the exact breakdowns needed for personal cost analysis and workflow analysis. The user wants to answer questions like:

- How many tokens did I use today, this week, or this month?
- Which project consumed the most usage?
- Which model consumed the most usage?
- What would this have cost at checked-in API prices?
- How much usage is cached input versus uncached input or output?
- Can I view this inside VS Code without opening a separate tool?

The project is a local analytics tool for personal Codex usage. It is not a cloud billing source of truth.

## Day 0 User

The first user is a developer who:

- runs Codex locally;
- has Codex JSONL session files on disk;
- wants exact local history, not only dashboard summaries;
- is comfortable installing a VS Code extension;
- cares about privacy and does not want logs uploaded.

This matters because the product can optimize for local-first behavior and developer transparency instead of multi-tenant cloud concerns.

## First MVP Boundary

The correct first MVP was a Python CLI, not a VS Code extension.

MVP:

- automatically discover Codex session files;
- parse token usage from JSONL;
- avoid double counting cumulative token records;
- group by day, hour, project, model, and session;
- estimate API-equivalent USD from checked-in pricing;
- output terminal, JSON, CSV, and a local HTML report.

Non-goals:

- no Marketplace publishing;
- no bundled runtime;
- no live pricing fetch;
- no cloud sync;
- no settings-heavy UI;
- no pandas or charting stack in the default path.

Future me: "Can I make a VS Code plugin in Python?" was the wrong first question. The right first question was "Where should the source of truth live so every future UI can reuse it?"

## Key Risks

Token accounting risk: Codex records cumulative token totals. Summing every record would overcount. The parser must calculate positive deltas.

Project identity risk: session metadata can be missing or stale. Project grouping needs canonical identity, aliases, and later transition detection.

Pricing risk: prices change over time. A single global pricing table would make historical reports misleading after future rate changes.

Privacy risk: JSONL logs may contain sensitive prompts and paths. The extension must stay local, avoid telemetry, and avoid uploading logs.

Runtime risk: a local `uv run` wrapper works for development but fails for normal users. Marketplace users need a bundled runtime strategy.

Sync risk: a naive file overwrite can destroy a conversation. Sync needs selected scope, backups, and conflict detection.

## Day 0 Architecture Sketch

```text
Codex session JSONL files
  -> Python parser
  -> usage records
  -> aggregation and pricing
  -> CLI outputs
  -> HTML report
  -> later VS Code wrapper
```

The core bet: keep all domain logic in Python, then let VS Code own only extension concerns.

## Day 0 Acceptance Criteria

The MVP is successful when:

- it finds sessions without a manual path;
- one fixture proves cumulative token deltas are counted correctly;
- one fixture proves missing token info is ignored;
- one fixture proves project fallback works when git metadata is missing;
- JSON and CSV output are stable enough for the future extension to consume;
- the HTML report works offline and has no remote assets.

