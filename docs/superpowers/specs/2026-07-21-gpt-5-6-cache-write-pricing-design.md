# GPT-5.6 Cache-Write Pricing Design

Date: 2026-07-21

## Goal

Account exactly for the cache-write tokens now recorded in local Codex JSONL so API-equivalent GPT-5.6 USD estimates no longer price those tokens as ordinary input.

This design supersedes the cache-write limitation in `2026-07-09-gpt-5-6-pricing-design.md`. The earlier design correctly avoided guessing, but current Codex events and the public Codex protocol now expose a distinct cache-write token count.

## Evidence And Root Cause

OpenAI's current pricing contract has four GPT-5.6 API token categories: input, cached input, cache write, and output. Cache writes cost 1.25 times the ordinary input rate. For requests over 272,000 input tokens, the existing GPT-5.6 long-context contract doubles all input rates, including cache writes, and multiplies output by 1.5.

Current Codex token-count events include `cache_write_input_tokens`. The public Codex source maps the API's `input_tokens_details.cache_write_tokens` directly into that field and describes it as the number of input tokens written to the prompt cache.

The plugin undercounts API-equivalent USD because `TokenUsage.from_mapping()` drops `cache_write_input_tokens`. `uncached_input_tokens` therefore combines ordinary input and cache writes, and `estimate_cost()` prices both at the ordinary input rate. The plugin is not missing the whole cache-write charge; it is missing the 25 percent uplift on those tokens.

Official sources:

- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [Prompt caching FAQ](https://developers.openai.com/api/docs/guides/prompt-caching#frequently-asked-questions)
- [GPT-5.6 Sol model card](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [Codex cache-write event contract](https://github.com/openai/codex/blob/661339bb0941c055602688a83bcc8f72be21b54d/sdk/typescript/src/events.ts)
- [Codex API-to-protocol mapping](https://github.com/openai/codex/blob/661339bb0941c055602688a83bcc8f72be21b54d/codex-rs/codex-api/src/sse/responses.rs)
- [Codex credit rate card](https://learn.chatgpt.com/docs/pricing#what-are-tokens-and-credits)

## Approaches Considered

### 1. Preserve and price the explicit field end to end

Add cache-write tokens to the domain model, parser deltas, persistent cache, aggregation, exports, and reports. Add an explicit API cache-write rate while keeping Codex credits on the existing input rate.

This is the chosen approach. It follows the upstream contract, remains exact, and supports future GPT families without inference.

### 2. Infer cache writes from non-cached input

Treat all `input_tokens - cached_input_tokens` as cache writes for GPT-5.6. This requires fewer schema changes but is wrong whenever a request contains ordinary uncached input. It also contradicts the existing exact-accounting guardrail.

Rejected.

### 3. Keep the current estimate and document the undercount

This avoids a migration but leaves a known error even though the required local field is available.

Rejected.

## Token Contract

Extend `TokenUsage` with:

```text
cache_write_input_tokens: int = 0
```

The token categories have these relationships:

```text
uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
ordinary_input_tokens = max(0, input_tokens - cached_input_tokens - cache_write_input_tokens)
```

`uncached_input_tokens` retains its current meaning and includes cache writes. This preserves compatibility for Codex credits and existing exports. `ordinary_input_tokens` is the API-pricing category that excludes both cache reads and cache writes.

Parsing, addition, positive cumulative deltas, dictionary serialization, aggregation, and cache round trips must all preserve the new field. Missing fields in older JSONL remain zero for backward compatibility.

## API Pricing Contract

Extend `ModelRate` and `CostBreakdown` with an explicit cache-write rate and cost component. A model without a published cache-write premium falls back to its ordinary input rate, so pre-GPT-5.6 behavior remains unchanged even if a log contains the field.

For GPT-5.6 standard API pricing:

| Model id | Ordinary input / 1M | Cached input / 1M | Cache write / 1M | Output / 1M |
| --- | ---: | ---: | ---: | ---: |
| `gpt-5.6-sol` | $5.00 | $0.50 | $6.25 | $30.00 |
| `gpt-5.6-terra` | $2.50 | $0.25 | $3.125 | $15.00 |
| `gpt-5.6-luna` | $1.00 | $0.10 | $1.25 | $6.00 |

For retained request events over 272,000 input tokens:

| Model id | Ordinary input / 1M | Cached input / 1M | Cache write / 1M | Output / 1M |
| --- | ---: | ---: | ---: | ---: |
| `gpt-5.6-sol` | $10.00 | $1.00 | $12.50 | $45.00 |
| `gpt-5.6-terra` | $5.00 | $0.50 | $6.25 | $22.50 |
| `gpt-5.6-luna` | $2.00 | $0.20 | $2.50 | $9.00 |

The existing request-level threshold remains unchanged: exactly 272,000 input tokens uses standard pricing, while 272,001 uses long-context pricing for the full retained event.

API-equivalent cost becomes:

```text
ordinary input cost
+ cached-input read cost
+ cache-write cost
+ output cost
```

## Codex Credit Contract

Do not add a cache-write credit rate. The public Codex rate card defines only input, cached input, and output credits. Cache writes remain part of `uncached_input_tokens` and use the published input-credit rate.

This intentional API-versus-credit difference belongs in the pricing layer and documentation, not in parser-specific behavior.

## Persistent Cache Migration

Add `cache_write_input_tokens integer not null default 0` to cached usage records. Bump both the cache schema version and parser cache version so every available source JSONL is reparsed and backfilled.

The cache preserves records for source files that have gone missing. Those legacy retained rows cannot be reparsed. During migration they receive zero for the new field through the column default, and the existing retained-missing warning will explicitly state that newer token classifications may be unavailable until the source file is restored. This is an evidence limitation, not an inferred value.

Newly parsed and newly retained rows preserve the exact field.

## Reporting

Expose cache writes without making them look like cache hits:

- CSV adds `cache_write_input_tokens` and `ordinary_input_tokens` while retaining `uncached_input_tokens`.
- Terminal and HTML detail tables rename `Cached` to `Cache Read` and add `Cache Write`.
- Serialized API cost breakdowns add `cache_write_input_usd`.
- Cache Hit Share continues to use cached reads only; cache writes do not increase it.
- Pricing notes explain that cache writes affect API-equivalent USD but currently have no separate Codex-credit category.

Update the checked-in dashboard image if the visible table header changes.

## Documentation And Architecture Record

Update the root and extension READMEs to remove the claim that local cache-write counts are unavailable. Update the Unreleased changelogs with the corrected accounting behavior.

Add ADR 0015 for the durable token-category contract: explicit upstream usage categories are preserved end to end, API and Codex-credit categorizations may intentionally differ when their official rate cards differ, and missing categories must not be inferred.

Target release version `0.1.37`; do not tag or publish until the implementation is reviewed and release is explicitly approved.

## Tests

Add regression coverage for:

- mapping, addition, positive deltas, and serialization of cache-write tokens;
- parser retention of cumulative `cache_write_input_tokens` deltas;
- aggregation across records and models;
- standard GPT-5.6 Sol, Terra, and Luna cache-write API rates;
- exactly 272,000 versus 272,001 input tokens, including doubled cache-write rates;
- pre-GPT-5.6 fallback to the ordinary input rate;
- unchanged Codex credit totals when cache writes are present;
- cache schema rebuild and round-trip persistence;
- migration of retained missing rows with the documented zero/default limitation;
- CSV, terminal, and HTML cache-read/cache-write output;
- removal of stale documentation claims.

Run the complete Python and VS Code extension test suites. Render the dashboard and inspect it at desktop and narrow widths to verify that the additional column remains readable and does not overlap adjacent content.

## Out Of Scope

- Changing Codex credit rates without an official cache-write credit category.
- Inferring cache writes for source records that do not expose the field.
- Changing the GPT-5.6 long-context threshold or model matching rules.
- Fetching live prices at report time.
- Repricing unknown model ids by family prefix.
