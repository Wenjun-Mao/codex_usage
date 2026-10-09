# ADR 0049: Credit Balances And Saturated Allowance Fits

## Status

Accepted on 2026-10-02. Extends ADRs 0044 and 0046.

## Context

An account can exhaust included allowance, continue on credits, and later resume
included allowance after a reset. The existing rate-limit probe already returned
credit metadata, but its quota-only projection discarded the balance. Estimated
Standard credits in token tables therefore were not observed account debits.

The monetary estimator also paired increasing local cost with repeated 100%
readings. Their percentage-bin median could inflate the inferred included
allowance: a synthetic $1,500 fit became $1,660 after additional cost at 100%.
This is a saturation problem at the estimator layer, not a pricing-rate error.

OpenAI documents optional credit metadata separately from earned resets in the
[App Server protocol](https://learn.chatgpt.com/docs/app-server). Its
[pricing guidance](https://learn.chatgpt.com/docs/pricing) distinguishes included
limits from credit-funded usage and notes shared usage and speed-dependent rates.

## Decision

- Capture credit metadata from the existing read-only `account/rateLimits/read`
  response; add no RPC, model request, refresh-on-view, or capture frequency.
- Ledger schema 5 adds one credit observation per live quota read, with exact
  decimal text, nullable availability/unlimited flags, and allowlisted diagnostic
  codes. Missing or invalid metadata remains unknown, never zero. Repeated bucket
  balances must agree numerically; conflicting balances are unavailable, not summed
  or chosen arbitrarily. No account identifiers or raw response content are saved.
- Keep credit balances independent of quota-window identity, banked-reset counts,
  token-based Standard credit estimates, and API-equivalent dollars. A quota reset
  does not reset credit history. Capture begins prospectively; historical or
  manually remembered balances are not manufactured as observations.
- Balance differences are exact, account-wide **net changes**, not authenticated
  per-project bills. Increases may be reloads, grants, refunds, corrections, or
  scope changes. Missing captures, unlimited readings, and plan changes interrupt
  the adjacent-reading delta. Other devices and billing scopes remain possible.
- End each monetary fit strictly before its first raw `used_percent >= 100`
  observation. A pinned meter cannot identify which later dollars are included,
  credit-funded, or active-turn grace. Exclude that tail even if later small meter
  corrections report 99%. A genuine reset starts a new fit under existing reset
  segmentation. Near-full fractional readings below 100 remain eligible.
  Preserve the earliest raw full-meter timestamp independently of the selected
  same-timestamp point; conflict deduplication must not erase saturation evidence.
- Preserve the complete raw quota window for reset evidence and audit. Use only
  fit-eligible costs for sufficiency, pricing coverage, confidence, and fit dates;
  disclose excluded observations inside window details. Ordinary language/image
  token totals and price estimates are unchanged. This cutoff is conservative
  evidence handling, not a claim that every response at 100% was credit-funded.
- Show a compact balance in the existing Plan Allowance heading. Do not add a
  standing funding-state sentence or historical "again" wording. Move the two
  caution paragraphs into existing diagnostics; balance history stays inside
  existing folded capture details. Unknown balances are hidden from the heading;
  older known balances are explicitly marked last known. Timestamps use the
  configured local timezone and numeric precision is inspectable on hover.
- Report materialization revision 5 and HTML revision 23 invalidate derived views
  without changing the event-cost pricing revision. Warm views query bounded
  balance status, not credit history or historical allowance payloads. Credit
  freshness participates in HTML cache identity independently of quota freshness.
  A partial index locates the last known balance without scanning intervening
  missing/invalid captures.

## Rejected Alternatives

- Inferring actual balance deductions or cash value from Standard token credits
  conflates included usage, speed modes, and unobserved account-wide activity.
- Using `hasCredits` as proof of active credit spending confuses available funds
  with observed use. A zero remaining display alone cannot establish payment.
- Fitting the post-full plateau, or merely hiding its changed result in the UI,
  retains the estimator's identification failure.
- Dropping raw full-meter observations would lose reset and audit evidence.
- A new expanded credits block or funding-state line adds repetition to the UI.

## Consequences And Guardrails

Schema-4 ledgers are backed up before additive migration; old read-only reports
remain available without credit data. Old estimates with too few pre-full bins
may lose sufficiency, using the existing same-series fallback rather than
manufacturing a full-allowance value. Monetary histories can change accordingly.

Tests cover exact decimals, duplicate/conflicting buckets, missing/invalid values,
unlimited balances, balance increases, resets, preserved migration evidence,
pre-full fit invariance, ignored post-full unpriced cost, untouched raw points,
bounded history, fresh/stale cache identity, and no warm-view history loading.
Browser checks cover folded content, local time, responsive header layout, and
no additional standing paragraphs.

Credit-depletion pace remains a follow-up after collecting balance observations.
It must use observed net decreases, not token credit estimates, and must not
continue projecting an old credit-spending period after allowance resumes.
Historical balance recovery and exact response-level billing attribution remain
unimplemented; this decision does not establish either capability.

ADR 0054's approved unpublished extension separately exposes full retained
prospective balance evidence in Usage & Allowance Breakdown, with original
intervals, unknown continuity and account-wide scope. This extends inspection,
not capture/backfill, funding attribution or this section's compact Plan
Allowance heading/disclosure policy.
