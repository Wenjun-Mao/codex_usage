# ADR 0046: Model Category Valuations And Standard Credit Estimates

## Status

Accepted on 2026-09-25.

## Context

Model Details showed aggregate token and price totals without explaining their
categories. Repricing an aggregate with one rate would be wrong across effective
dates and request-level long-context thresholds. The GPT-6 Sol and Luna credit
rates became public after their API rates were added. The ledger does not carry
a reliable Standard/Fast speed marker.

## Decision

Model Details uses one compact comparison row and a native disclosure per model.
Its category rows show Total, Input subtotal, Cached input, Regular input,
reported Cache write, and Output, each with token count, API-equivalent USD, and
estimated Standard Codex credits. Input is the sum of the three input categories;
Total is Input plus Output. The renderer reads category valuations accumulated
from individual usage events. It never multiplies aggregate tokens by a current
rate. Unpriced category token counts accumulate separately; a missing rate is
shown as unavailable and a mixed category as partial.

Codex credits charge reported cache-write tokens at the ordinary input rate as
part of uncached input. The category contribution is displayed separately for
explanation, with no separate cache-write surcharge. The existing combined
`uncached_input_credits` field remains the sum of regular and cache-write input
credits for compatibility.

GPT-6 Sol and Luna Standard credit schedules begin at 2026-09-22 00:00 UTC,
the earliest conservative date supported by the published launch day. This
midnight boundary is an inference from a date-only announcement, not a claim
about the exact rollout instant. Earlier activity stays unpriced. Fast is 2.5x
Standard where supported, but the ledger cannot identify it, so the report
labels its values Standard estimates rather than claiming actual billed credits.

## Rejected Alternatives

- Adding all categories as wide columns would make Model Details difficult to
  scan, especially in the VS Code webview.
- Repricing aggregated usage would lose effective-date and request-level rates.
- Treating unknown prices as zero would imply complete coverage.
- Applying the Fast multiplier without source evidence would overstate some
  activity and claim a billing precision the ledger does not have.

## Consequences And Guardrails

The shared HTML serves desktop and VS Code. Other aggregate tables keep their
Share bars. Pricing and rendered-report cache revisions must advance with these
semantics. Tests cover launch boundaries, category conservation, long-context
events, missing rates, and the disclosure structure.

Sources: [Codex credit rate card](https://learn.chatgpt.com/docs/pricing),
[2026-09-22 launch announcement](https://learn.chatgpt.com/docs/changelog).
