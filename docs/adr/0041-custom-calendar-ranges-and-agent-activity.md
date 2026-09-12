# ADR 0041: Custom Calendar Ranges And Ledger-Only Agent Activity

## Status

Accepted for version 2.5.0 on 2026-09-07

## Context

The durable usage ledger already stores parser-produced positive usage deltas,
task parent relationships, titles, roles, and project context. Reports could
only select a small set of named ranges, and their cache key used the symbolic
range name rather than its resolved local-calendar bounds. A `today` or `month`
result could therefore remain cached after midnight without a ledger change.
Users also lacked a compact view of activity across agent tasks and had no way
to export complete selected-range detail without re-reading Codex task files.

## Decision

The agent owns one canonical report-range value. It accepts named presets or a
`custom` pair of inclusive `YYYY-MM-DD` local dates, resolves the end date to
the next local midnight, rejects malformed, reversed, and future selections,
and carries friendly display text plus a UTC-bound cache identity. Moving
presets include their resolved bounds in that identity. Custom ranges retain
daily presentation through 90 days and use the existing script-free Week/Month
view for longer periods.

Agent Activity is derived from the same filtered `UsageRecord` collection used
by the report. It uses durable `ledger_tasks` metadata only to resolve nested
agent roots and friendly labels; cycles and missing parents use deterministic
safe fallbacks. Each positive ledger delta counts as one response, which can
include internal or tool-driven model cycles and is not a user-message count.
The dashboard presents daily totals and at most the 50 highest-token agents;
the authenticated CSV endpoint returns every agent-by-day row. Native and VS
Code clients save that data through their host-owned dialogs, while bearer
tokens remain outside webviews.

## Consequences And Guardrails

No ledger schema, persistent aggregate table, capture behavior, transcript
scan, or valuation pass is added. Range selection, Agent Activity, and CSV
export query SQLite only. Daily, per-agent, role, root-task, and agent-day
totals must each conserve the selected raw token categories and positive-delta
response count. Health and status advertise the additive capabilities while
the API remains version 1, allowing independently updated clients to present a
clear collector-update error. The renderer revision invalidates 2.4.x HTML.

For version 2.7.1, the Daily Summary remains immediately visible while the
bounded per-agent table is a closed-by-default native `details` disclosure.
Its summary remains keyboard-operable, and presentation does not reduce or
otherwise change the complete selected agent-day CSV contract.
