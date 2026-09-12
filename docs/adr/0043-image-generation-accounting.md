# ADR 0043: Independent Image Generation Accounting

## Status

Accepted for version 2.7.0 on 2026-09-12.

## Context

Codex image generation is a billable tool activity, not a language response.
The existing ledger, token totals, cost totals, response counts, and project-turn
economics intentionally describe language-model activity. Folding image calls
or image token estimates into those aggregates would make their conservation
rules and cost-per-turn metrics false.

Codex can expose different grades of evidence for one image operation. Response
usage is stronger than a tool argument, which is stronger than signed C2PA
metadata, which is stronger than merely observing activity. Some fields can be
missing independently, and an observed model family does not establish its
variant, quality, input usage, or billed price.

## Decision

Create a dedicated image-operation domain and, in the durable ledger, a
separate `ledger_image_events` table. One operation is the stable pair of source
generation and tool-call identity. Distinct call identities, including retries,
are distinct operations. Replaying a source generation replaces its owned
events atomically, making parser replay idempotent. Output count remains a
separate measure.

The image event retains timestamp, task and root-task identity, role, turn,
verified project context, operation kind, outcome, dimensions/format when
observable, raw model evidence, normalized model identity, and raw upstream
usage. It must never retain prompts, revised prompts, input or generated image
paths, image bytes, base64 data, or other image content.

Evidence is retained as observations and selected in this order:

1. Exact upstream response model and usage fields.
2. A Codex image-tool invocation naming a model.
3. Signed C2PA software-agent name and version.
4. Activity-only inference.

Conflicting evidence is retained and disclosed; it cannot support an exact
valuation. Signed `gpt-image` versions `2.0` and `2.5` normalize respectively
to GPT Image 2 and GPT Image 2.5. The latter has an unknown variant unless
stronger evidence names Sunburst or Flare. API IDs and dated snapshots for
`gpt-image-2`, `gpt-image-2.5-sunburst`, and `gpt-image-2.5-flare` are
recognized. A future `gpt-image-2.x` remains visible as image activity but is
not aliased or priced until an explicit schedule entry exists.

Use a separate, effective-dated image schedule. The 2026-09-12 schedule records
documented API rates of $5.00/M text input, $1.25/M cached text input, $8.00/M
image input, $2.00/M cached image input, and $30.00/M image output for GPT Image
2 and GPT Image 2.5. GPT Image 2 credits use 125/M, 31.25/M, 250/M text output,
200/M image input, 50/M cached image input, and 750/M image output. GPT Image
2.5 uses the same displayed credit conversion only as a **credit-equivalent
estimate** until a Codex credit schedule identifies that family. Calculated
prices are not persisted, so schedule corrections only invalidate reports.

Every image valuation is one of:

- **Exact**: complete upstream usage plus a matching effective schedule.
- **Estimated range**: a model-specific documented output estimator bounds the
  result. The disclosure explicitly lists excluded input components.
- **Unpriced**: evidence cannot support a bound without an assumption.

Ranges have no midpoint and do not join any scalar language cost total. GPT
Image 2 calculator semantics cannot estimate GPT Image 2.5; estimators are
family/variant specific and may return Unpriced when their own documented
contract is unavailable.

## Consequences And Guardrails

Language `TokenUsage`, language `CostBreakdown`, `CreditBreakdown`, response
counts, and Project Economics remain unchanged. Image reports aggregate their
own operations, outputs, outcomes, families, exact amounts, bounded ranges, and
unpriced coverage. Their report cache identity includes an image-pricing
revision.

The capture layer must treat unsigned, malformed, or conflicting metadata as
low-confidence evidence; it must not trust file names. It uses bounded metadata
readers and a bounded parser that skips content payloads. Reports consume only
the durable ledger and do not reopen JSONLs or image files.

Current Codex rollouts encode image generation as an exact nested
`tools.image_gen__imagegen(...)` invocation inside an `exec` custom-tool call,
followed by an Image Generation Extension completion. The parser recognizes
that wrapper contract without treating arbitrary command text containing the
word “imagegen” as activity. It retains only call identity and non-content
metadata, and uses the exact generated-artifact basename solely to read a
bounded PNG header and signed C2PA software-agent assertion.

The bounded 2026-09-12 live acceptance fixture reconciles ten successful calls
and ten outputs across two projects: six fresh generations and four
reference/edit operations. Classification depends on effective reference
inputs, not mere option-key presence. A nonempty reference path collection or
a positive prior-image count is an edit; explicit `null` reference options are
a fresh generation. The fixture is observational evidence, not a special-case
classifier rule.

Upgrades preserve the schema-8 language cache and its parser checkpoints.
Historical image recovery is a separate, resumable artifact-first backfill:
validated generated-image directories nominate task IDs, only the exact owning
rollout filename may then be read, and each capture consumes one bounded parser
slice. Durable status distinguishes pending, complete, and partial coverage;
missing or ambiguous owning rollouts remain unavailable rather than becoming
fabricated zero activity. Rebuilding recovered image events never rebuilds or
changes language events.

Clients require the additive `image-generation-accounting` capability before
requesting the combined report and show an actionable collector-update message
when it is absent.

The rate and family contracts are grounded in the official OpenAI model pages:
GPT Image 2 documents the family and snapshots, while GPT Image 2.5 Sunburst
documents matching token rates, its separate quality contract, and that the GPT
Image 2 calculator does not estimate GPT Image 2.5 token consumption.

## Rejected Alternatives

- Treating image calls as language responses would distort language totals and
  per-turn economics.
- Inferring a quality or cost from pixels, dimensions, file size, latency, or a
  filename would manufacture billing precision.
- Mapping every future `gpt-image-2.x` identifier to GPT Image 2 would silently
  apply stale pricing.
- Persisting calculated prices would require historical recapture after official
  rate corrections.
