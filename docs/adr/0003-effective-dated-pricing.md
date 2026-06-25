# ADR 0003: Effective-Dated Pricing

Status: Accepted

Date: 2026-06-16

## Context

Model prices can change. If reports use one current price table for all history, old usage can be repriced incorrectly after a future rate change.

## Decision

Store checked-in rate schedules with `effective_from` timestamps. Price each usage record with the API USD and Codex credit rates active at that record's timestamp.

## Alternatives Considered

- Use one current flat table. Simpler, but historically misleading.
- Fetch live pricing at runtime. More current, but adds network behavior, source drift, failures, and privacy questions.
- Convert Codex credits to USD. Useful, but different from official API-equivalent USD and not always stable.

## Consequences

Historical reports remain stable when future rates are added. Adding a price change means appending a new effective-dated row instead of editing old rows.

## Guardrails

Keep API USD and Codex credits separate. Do not fetch pricing over the network in normal reporting.

Model matching is exact by checked-in model id or explicit alias. Do not price an unknown future variant such as `gpt-5.6-pro` by substring-matching a base model such as `gpt-5.6`; leave it visible but unpriced until official rates are checked in.
