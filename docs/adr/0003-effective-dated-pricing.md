# ADR 0003: Effective-Dated Pricing

Status: Accepted

Date: 2026-06-16

## Context

Model prices can change. If reports use one current price table for all history, old usage can be repriced incorrectly after a future rate change.

## Decision

Store checked-in rate schedules with `effective_from` timestamps. Price each usage record with the API USD and Codex credit rates active at that record's timestamp.

Effective pricing can also depend on request-level token volume for the retained usage event. For example, GPT-5.6 API pricing uses a request-pricing contract: exactly 272,000 input tokens stays on the short-context rates, while more than 272,000 input tokens prices the full retained request event at long-context API rates. This volume-sensitive contract applies to API USD only; Codex credit rates remain flat unless an official rate card adds a separate contract.

## Alternatives Considered

- Use one current flat table. Simpler, but historically misleading.
- Fetch live pricing at runtime. More current, but adds network behavior, source drift, failures, and privacy questions.
- Convert Codex credits to USD. Useful, but different from official API-equivalent USD and not always stable.

## Consequences

Historical reports remain stable when future rates are added. Adding a price change means appending a new effective-dated row instead of editing old rows.

Long-context or other request-level contracts must be attached to effective rate entries, not implemented as downstream one-off model-name checks.

## Guardrails

Keep API USD and Codex credits separate. Do not fetch pricing over the network in normal reporting.

Model matching is exact by checked-in model id or explicit alias. The official `gpt-5.6` alias may map to Sol because that alias is checked in explicitly. Do not price an unknown future variant such as `gpt-5.6-pro`, `gpt-5.6-mini`, or a wrapper name by substring-matching a base model such as `gpt-5.6`; leave it visible but unpriced until official rates are checked in.
