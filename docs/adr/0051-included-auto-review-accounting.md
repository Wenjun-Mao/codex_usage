# ADR 0051: Included Auto-review Accounting

Status: Accepted

Date: 2026-10-07

## Context

Tibo's [October 6 announcement](https://x.com/thsottiaux/status/2107368734981517634)
made Auto-review free for users signed in with ChatGPT. The later
[roundup](https://x.com/thsottiaux/status/2107575657014468879) explicitly says it
does not consume plan usage. The [community announcement](https://community.openai.com/t/free-auto-review-day-2-of-28-days-of-quality-of-life-improvements-or-a-full-reset/1403525/17)
also records that scope. Ordinary code review and custom API reviewer calls are
not covered by this policy.

Captured approval reviews use the dedicated `codex-auto-review` model identity.
Previously this exact model had no public API or Codex credit rate. Reports did
not add guessed charges, but counted its tokens as unpriced. Consequently,
otherwise usable allowance windows could fail the pricing-completeness gate.

## Decision

- Keep all captured tokens, response counts, subagent ownership and raw ledger
  history unchanged.
- Add an effective-dated zero Standard-credit rate for exactly
  `codex-auto-review`. This is subscription valuation, not an API billing rule.
- Keep public API-equivalent cost unavailable for this model. Its tokens remain
  API-excluded; a free subscription feature is not a published zero USD API rate.
- For allowance calibration and calibrated pace only, known included reviews
  contribute zero quota-relevant cost and zero unknown-cost tokens. Full and
  indexed calculations share that rule.
- Use **2026-10-06 07:14 UTC** as a conservative evidence boundary: the next full
  minute after the original post displayed at 03:13 EDT in Safari. This is not
  a claim about the exact backend rollout time. Earlier records retain unknown
  pricing, and unknown variants remain unpriced.
- Advance the pricing-as-of and rendered-report revisions so existing derived
  costs and HTML are rebuilt without rewriting source events.

The ledger does not retain per-event login mode. Codex credit estimates already
describe subscription Standard-credit equivalents, not measured paid debits.
This change does not infer API-key billing, erase unknown API charges, or extend
the policy to an arbitrary agent using a normally priced model. Reconsider the
identity contract if later telemetry uses public model IDs for approval reviews.

## Alternatives And Guardrails

Dropping review events would lose telemetry and distort storage/task accounting.
Adding a zero API price would confuse included subscription usage with public API
pricing. Exempting all subagents or all models containing `review` would exempt
ordinary paid work. Backdating the policy to all history would invent a past
entitlement. None of these alternatives is accepted.

Tests cover the cutoff, timezone/model normalization, unknown variants, ordinary
review pricing, unchanged API totals/tokens, captured-ledger full/indexed parity,
valid allowance fits, warm cache reuse, and old derived-cost invalidation. No
normal report path fetches live pricing or reads authentication credentials.
