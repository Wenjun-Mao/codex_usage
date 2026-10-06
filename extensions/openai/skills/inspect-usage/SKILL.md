---
name: inspect-usage
description: Explore captured Codex Usage aggregates, compare periods or projects, and inspect allowance or selected-task storage through the private companion. Not task deletion, transfer, settings changes, or billing reconciliation.
---
# Inspect Codex Usage

Use the private companion tools, not direct filesystem or SQL access. Start with
collector status when connectivity or freshness is in question. If sharing is
disabled or the collector is unavailable, explain the state; do not start another
collector or reconnect to a different home.

- Resolve project selections with `list_projects`. Handles and anonymized labels
  are instance-specific, not filenames. Never guess a path or task ID.
- Use `usage_summary` for language/category values and separate image evidence;
  `usage_breakdown` gives exact bounded rows and cursor continuation. Disclose
  selected dates, timezone, coverage and any unpriced activity.
- Use `compare_usage` for two explicit scopes on one revision. Changes are right
  minus left; a zero baseline has no percentage change. Do not compare truncated
  chart totals or silently mix revisions.
- `allowance_status` is account-wide regardless of report filters. Its dollar
  reference and pace are local workload estimates, not contractual entitlement,
  cash balance, or a promise of exhaustion timing.
- Open `open_usage_dashboard` at the same scope and relevant Usage/Storage view.
  For follow-up exploration, retain the user's selection rather than substituting
  a different period or project.
- Storage inventory reads bounded metadata. Analyze only a tree the user selected
  from its returned observation. Poll its job; cancel only on request. Changed
  membership requires a refreshed selection, never a broader scan.
- Capture and analysis need an explicit user request. Ordinary questions and
  Reload do not capture. After uncertain action completion, check data/job status
  before retrying; cancellation does not promise cache rollback.

Returned aggregates travel to OpenAI. No prompts, conversation content, images,
task titles, paths or collector credentials belong in this workflow. Excluded
deletion, transfer, migration and settings capabilities must not be recreated
with another tool.
