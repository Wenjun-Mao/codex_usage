# GPT-5.6 Pricing Support Design

Date: 2026-07-09

## Goal

Price locally recorded Codex usage for the generally available GPT-5.6 family without weakening the dashboard's effective-dated, exact-model pricing contract.

## Context

Codex session JSONL records GPT-5.6 selections with tier-specific model ids such as `gpt-5.6-sol`. It records reasoning effort separately, including `ultra`. The parser and cache already preserve both fields.

OpenAI published GPT-5.6 API pricing on 2026-06-26. Sol, Terra, and Luna became generally available in Codex on 2026-07-09, when the public Codex credit rate card established GPT-5.6 credit values. No authoritative source establishes Codex credit rates for the 2026-06-26 to 2026-07-08 preview interval.

The GPT-5.6 model cards also define request-level long-context API pricing. A request with more than 272,000 input tokens is billed at long API rates for the full request: 2x uncached input, 2x cached input, and 1.5x output. Exactly 272,000 input tokens remains short-context pricing; 272,001 input tokens uses long-context pricing.

Official sources:

- [GPT-5.6 Sol model card](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [GPT-5.6 Terra model card](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.6 Luna model card](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [API pricing](https://developers.openai.com/api/docs/pricing)
- [Codex token-based credit rate card](https://help.openai.com/en/articles/20001106-codex-rate-card-2)

## Decision

Add exact, effective-dated pricing rows for all three official GPT-5.6 model ids, plus the official `gpt-5.6` alias to Sol. Do not add family-prefix or substring matching. Other variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names remain visible but unpriced until official rates are checked in.

API USD rows are effective from `2026-06-26T00:00:00Z`. Codex credit rows are effective from `2026-07-09T00:00:00Z`. Keep `PRICING_AS_OF = "2026-07-09"` and release version `0.1.32`.

| Model id | Alias | API input / 1M | API cached input / 1M | API output / 1M | Credit input / 1M | Credit cached input / 1M | Credit output / 1M |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.6-sol` | `gpt-5.6` | $5.00 | $0.50 | $30.00 | 125 | 12.5 | 750 |
| `gpt-5.6-terra` | none | $2.50 | $0.25 | $15.00 | 62.5 | 6.25 | 375 |
| `gpt-5.6-luna` | none | $1.00 | $0.10 | $6.00 | 25 | 2.5 | 150 |

When a retained usage event has `usage.input_tokens > 272_000`, price that full retained event at these long-context API rates:

| Model id | Long API input / 1M | Long API cached input / 1M | Long API output / 1M |
| --- | ---: | ---: | ---: |
| `gpt-5.6-sol` | $10.00 | $1.00 | $45.00 |
| `gpt-5.6-terra` | $5.00 | $0.50 | $22.50 |
| `gpt-5.6-luna` | $2.00 | $0.20 | $9.00 |

The long-context rule applies only to API-equivalent USD. Codex credits remain flat because the Codex rate card publishes only input, cached input, and output credit categories, not a long-context multiplier.

Reasoning effort is not part of the pricing key. Settings such as `ultra`, `max`, and `xhigh` may change how many tokens a task consumes, but all recorded tokens use the rate for their underlying model tier. The dashboard continues to group its model mix by model id only.

## Data Flow

No parser, cache schema, aggregation interface, report layout, or VS Code behavior changes are required:

1. `parser.py` reads `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, or the official `gpt-5.6` alias into `UsageRecord.model` and preserves effort separately.
2. The parser keeps only positive token-count deltas between cumulative events. A local privacy-preserving audit of 10 GPT-5.6 Sol session files covered 1,163 token-count events: all 1,148 retained positive-delta events exactly matched the event's request-level `last_token_usage`, while 15 zero-delta duplicate snapshots were already dropped.
3. `aggregation.py` passes each retained usage record's model, timestamp, and request-level event delta to `pricing.py`.
4. `pricing.py` resolves only an exact model id or explicit alias and selects the latest rate effective at the record timestamp.
5. The request-level long-context contract checks the retained event's `usage.input_tokens`, not a cumulative session or conversation total. Multiple short retained events in the same session cannot combine to trigger long-context pricing.
6. Reports include the newly priced usage in API-equivalent USD and Codex credit totals.

## Cache-Write Limitation

GPT-5.6 API cache reads receive the published 90 percent discount, which produces the cached-input rates above. OpenAI separately charges explicit cache writes at 1.25 times the uncached input rate.

Local Codex token-count events expose `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`, and `total_tokens`. They do not expose a distinct cache-write token count. The dashboard therefore continues to treat non-cached input as ordinary input and cached input as cache reads. It must not guess which non-cached tokens were explicit cache writes. Documentation will state that API-equivalent USD cannot include an unobservable cache-write uplift.

Codex credit estimates are unaffected by this limitation because the Codex rate card publishes only input, cached input, and output credit categories, matching the local token fields used by the dashboard.

## Supersession Note

ADR 0015, dated 2026-07-21, supersedes this design's cache-write limitation. Local Codex logs are now known to expose explicit `cache_write_input_tokens`; current API-equivalent USD uses the published cache-write rate while Codex credits retain the published ordinary input rate. The original exact model matching, API effective date `2026-06-26T00:00:00Z`, credit effective date `2026-07-09T00:00:00Z`, and 272,000-token long-context boundary remain unchanged.

## Tests

Add regression coverage that:

- verifies exact API and Codex credit rates for Sol, Terra, Luna, and the official `gpt-5.6` Sol alias;
- verifies API rates are available on 2026-06-26 while Codex credit rates are unavailable until 2026-07-09;
- verifies exactly 272,000 input tokens uses short-context API pricing;
- verifies 272,001 input tokens uses long-context API pricing for Sol, Terra, and Luna, covering uncached input, cached input, and output;
- verifies long-context API pricing does not change Codex credit estimates;
- parses and aggregates a `gpt-5.6-sol` record with `ultra` effort and confirms the model rate is unchanged;
- verifies two cumulative token events are priced as independent request-level retained deltas, so cumulative session totals cannot trigger long-context pricing;
- keeps unpublished GPT-5.6 variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names unpriced;
- preserves effective-date behavior around both GPT-5.6 API and Codex credit start dates.

Run the complete Python and VS Code extension test suites after implementation.

## Documentation And Release

Keep the Python package, VS Code extension manifest, npm lockfile root package, and both changelogs at `0.1.32`. Document GPT-5.6 family support, the official Sol alias, the request-level long-context boundary, separate API and Codex credit dates, event-level pricing reliability, and the cache-write limitation in the user-facing pricing notes.

Update ADR 0003 because the effective-pricing contract now explicitly allows rate selection to depend on both the event timestamp and request-level token volume.

After the implementation is merged and a release is approved, tag `v0.1.32`. The existing GitHub Actions workflow must test and package both Windows x64 and macOS Apple Silicon before publishing either VSIX to the Marketplace.

## Out Of Scope

- A reasoning-effort dashboard or separate `ultra` cost multiplier.
- Prefix, substring, or inferred pricing for unknown GPT-5.6 variants.
- Live pricing fetches.
- Parser, cache-schema, chart, or extension-command changes.
- Estimating API cache-write charges without a distinct local token field.
