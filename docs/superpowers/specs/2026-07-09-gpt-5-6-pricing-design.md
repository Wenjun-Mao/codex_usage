# GPT-5.6 Pricing Support Design

Date: 2026-07-09

## Goal

Price locally recorded Codex usage for the generally available GPT-5.6 family without weakening the dashboard's effective-dated, exact-model pricing contract.

## Context

Codex session JSONL now records GPT-5.6 selections with tier-specific model ids such as `gpt-5.6-sol`. It records reasoning effort separately, including `ultra`. The parser and cache already preserve both fields, but the checked-in pricing schedules intentionally leave GPT-5.6 unpriced because official rates were not available when the future-model guardrail was added.

OpenAI published GPT-5.6 pricing during the limited preview on 2026-06-26 and made Sol, Terra, and Luna generally available in Codex on 2026-07-09. OpenAI also publishes token-based Codex credit rates for all three tiers.

Official sources:

- [GPT-5.6 general availability and API pricing](https://openai.com/index/gpt-5-6/)
- [Codex token-based credit rate card](https://help.openai.com/en/articles/20001106-codex-rate-card-2)
- [GPT-5.6 preview pricing announcement](https://openai.com/index/previewing-gpt-5-6-sol/)

## Decision

Add exact, effective-dated pricing rows for all three official GPT-5.6 model ids. Do not add aliases or family-prefix matching.

| Model id | API input / 1M | API cached input / 1M | API output / 1M | Credit input / 1M | Credit cached input / 1M | Credit output / 1M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.6-sol` | $5.00 | $0.50 | $30.00 | 125 | 12.5 | 750 |
| `gpt-5.6-terra` | $2.50 | $0.25 | $15.00 | 62.5 | 6.25 | 375 |
| `gpt-5.6-luna` | $1.00 | $0.10 | $6.00 | 25 | 2.5 | 150 |

The rates are effective from 2026-06-26, when GPT-5.6 preview pricing was published. Set the checked-in pricing-table date to 2026-07-09, when the family became generally available.

Reasoning effort is not part of the pricing key. Settings such as `ultra`, `max`, and `xhigh` may change how many tokens a task consumes, but all recorded tokens use the rate for their underlying model tier. The dashboard continues to group its model mix by model id only.

## Data Flow

No parser, cache schema, aggregation interface, report layout, or VS Code behavior changes are required:

1. `parser.py` reads `gpt-5.6-sol`, `gpt-5.6-terra`, or `gpt-5.6-luna` into `UsageRecord.model` and preserves effort separately.
2. `aggregation.py` passes each usage record's model and timestamp to `pricing.py`.
3. `pricing.py` resolves only an exact model id or explicit alias and selects the latest rate effective at the record timestamp.
4. Reports include the newly priced usage in API-equivalent USD and Codex credit totals.

Generic or unknown variants such as `gpt-5.6`, `gpt-5.6-pro`, and `wrapper-gpt-5.6-sol` remain visible but unpriced. This preserves ADR 0003's future-model guardrail.

## Cache-Write Limitation

GPT-5.6 API cache reads receive the published 90 percent discount, which produces the cached-input rates above. OpenAI separately charges explicit cache writes at 1.25 times the uncached input rate.

Local Codex token-count events expose `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`, and `total_tokens`. They do not expose a distinct cache-write token count. The dashboard therefore continues to treat non-cached input as ordinary input and cached input as cache reads. It must not guess which non-cached tokens were explicit cache writes. Documentation will state that API-equivalent USD cannot include an unobservable cache-write uplift.

Codex credit estimates are unaffected by this limitation because the Codex rate card publishes only input, cached input, and output credit categories, matching the local token fields used by the dashboard.

## Tests

Add regression coverage that:

- verifies exact API and Codex credit rates for Sol, Terra, and Luna;
- verifies API-equivalent cost and credit calculations for representative token usage;
- parses and aggregates a `gpt-5.6-sol` record with `ultra` effort and confirms the model rate is unchanged;
- keeps generic and unknown GPT-5.6 variants unpriced;
- updates hypothetical-future-model report tests so they do not conflict with the newly supported family;
- preserves effective-date behavior before and after 2026-06-26.

Run the complete Python and VS Code extension test suites after implementation.

## Documentation And Release

Bump the Python package, VS Code extension manifest, npm lockfile root package, and both changelogs to `0.1.32`. Document GPT-5.6 family support and the cache-write limitation in the user-facing pricing notes.

No new ADR is required because the accepted effective-dated, exact-model pricing contract is unchanged. This release only adds official rows under that contract.

After the implementation is merged and a release is approved, tag `v0.1.32`. The existing GitHub Actions workflow must test and package both Windows x64 and macOS Apple Silicon before publishing either VSIX to the Marketplace.

## Out Of Scope

- A reasoning-effort dashboard or separate `ultra` cost multiplier.
- Prefix, substring, or inferred pricing for unknown GPT-5.6 variants.
- Live pricing fetches.
- Parser, cache-schema, chart, or extension-command changes.
- Estimating API cache-write charges without a distinct local token field.
