# GPT-5.6 Terra And Luna API Price Reduction Design

Date: 2026-07-30

## Goal

Apply OpenAI's reduced GPT-5.6 Terra and Luna API prices to usage recorded from
`2026-07-31T00:00:00Z` onward without changing historical estimates, GPT-5.6
Sol pricing, or Codex credit estimates.

## Evidence And Effective Date

OpenAI's live API pricing table now lists lower Standard, Batch, Flex, and Fast
mode rates for GPT-5.6 Terra and Luna. The plugin estimates Standard API pricing,
so this change uses the current Standard rows:

- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [GPT-5.6 Terra model card](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.6 Luna model card](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

At review time, the live pricing table contained the reduced rates while the
model cards and GPT-5.6 launch material still displayed the original rates. The
pricing page was last modified at `2026-07-31T00:11:28Z`, but OpenAI did not
publish a more precise billing-transition timestamp in the reviewed sources.

Use the user-approved effective boundary `2026-07-31T00:00:00Z`. This keeps
usage through July 30 on the original published rates and applies the current
pricing from the UTC day on which the live table changed.

## Approaches Considered

### 1. Append effective-dated rates

Keep the original Terra and Luna entries effective from June 26 and append new
entries effective from July 31. The existing pricing lookup selects the newest
entry whose timestamp is not later than the usage record.

This is the chosen approach. It follows ADR 0003, preserves reproducible
historical reports, and requires no new runtime behavior.

### 2. Replace the original rates

Editing the June 26 entries would be smaller, but every historical report would
be repriced as though the reduction existed at launch.

Rejected.

### 3. Fetch current pricing at report time

Live lookup could track future changes automatically, but would make local
reports network-dependent, non-reproducible, and vulnerable to source drift.

Rejected.

## API Pricing Contract

The original Standard rates remain effective from `2026-06-26T00:00:00Z`
through `2026-07-30T23:59:59.999999Z`:

| Model id | Ordinary input / 1M | Cached input / 1M | Cache write / 1M | Output / 1M |
| --- | ---: | ---: | ---: | ---: |
| `gpt-5.6-terra` | $2.50 | $0.25 | $3.125 | $15.00 |
| `gpt-5.6-luna` | $1.00 | $0.10 | $1.25 | $6.00 |

The reduced Standard rates apply from `2026-07-31T00:00:00Z`:

| Model id | Ordinary input / 1M | Cached input / 1M | Cache write / 1M | Output / 1M |
| --- | ---: | ---: | ---: | ---: |
| `gpt-5.6-terra` | $2.00 | $0.20 | $2.50 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $0.25 | $1.20 |

The existing request-level long-context contract remains unchanged. More than
272,000 input tokens doubles all input-category rates and multiplies output by
1.5 for the full retained usage event. The reduced long-context rates are:

| Model id | Ordinary input / 1M | Cached input / 1M | Cache write / 1M | Output / 1M |
| --- | ---: | ---: | ---: | ---: |
| `gpt-5.6-terra` | $4.00 | $0.40 | $5.00 | $18.00 |
| `gpt-5.6-luna` | $0.40 | $0.04 | $0.50 | $1.80 |

Exactly 272,000 input tokens remains short-context pricing. GPT-5.6 Sol keeps
its existing short- and long-context rates.

## Codex Credit Contract

Do not change `CODEX_CREDIT_RATE_SCHEDULE`. API-equivalent USD and Codex credits
are separate estimates with separate official sources. No reviewed source
establishes reduced Terra or Luna Codex credit rates.

Reasoning effort remains metadata and does not change the per-token rates.

## Implementation

Update `PRICING_AS_OF` to `2026-07-31` and add a named July 31 effective-date
constant. Append one Terra and one Luna API schedule entry using the existing
GPT-5.6 long-context request-pricing contract. Keep the June 26 entries intact.

The existing latest-applicable-entry lookup already supports this schedule
shape. No parser, cache schema, reporting schema, or network behavior changes
are required.

Update the root and extension READMEs so current rate examples use the reduced
values and explicitly state that the original rates remain applicable before
July 31. Historical changelog entries and earlier design records remain
unchanged.

Prepare release `0.1.41` with matching Python and VS Code extension metadata and
dated root and extension changelog entries.

## Tests

Add regression coverage for:

- original Terra and Luna rates one microsecond before the July 31 boundary;
- reduced rates exactly at and after the July 31 boundary;
- omitted `at` selecting the latest reduced rates;
- reduced short-context ordinary input, cached input, cache-write, and output
  costs;
- reduced long-context costs above 272,000 input tokens;
- unchanged GPT-5.6 Sol API rates;
- unchanged Terra and Luna Codex credit rates;
- updated `PRICING_AS_OF`, README contracts, changelogs, and release metadata.

Run the complete Python and VS Code extension test suites. The change has no
visual surface and does not require screenshot verification.

## Out Of Scope

- Changing Batch, Flex, or Fast mode estimates; the plugin currently reports
  Standard API-equivalent USD only.
- Changing Codex credit rates or included ChatGPT/Codex usage limits.
- Repricing usage recorded before `2026-07-31T00:00:00Z`.
- Fetching prices dynamically.
- Changing the long-context threshold, multipliers, alias mapping, or exact
  model matching.
