# ADR 0064: Paginated Session Accounting

Status: selected for the next candidate; parser/capture foundation implemented,
upgrade discovery, lineage audit and targeted repair not yet qualified.

## Context

A logical thread can continue in a new physical rollout file. Its opening
`total_token_usage` can repeat the cumulative usage already recorded in the
referenced history. Starting that file with no baseline incorrectly attributes
the entire inherited counter to one contemporary response and price tier.
Treating every file with the same thread ID as a duplicate also drops distinct
physical parts. Separately, a quota-only token-count event with a null cumulative
counter must not reset an established baseline to zero.

## Decision

Retain only the allowlisted history mode, outer metadata ordinal, logical fork
cutoff and history boundary fields. The boundary's historically named `thread_id`
identifies a **physical rollout**, not necessarily the logical task or immediate
fork parent. Canonical `rollout-<timestamp>-<logical UUID>[_<physical UUID>].jsonl`
filenames identify both; no serialized `rollout_id` field is assumed. A physical
page gets a stable source key across copies while retaining its logical task ID.
The original rollout (equal physical/logical IDs) and ordinary sources retain
their existing keys. Root/subagent attribution is unchanged.
Normalized synchronization retires an old missing key only when a current parser-
owned generation proves the same path, nonzero device/inode and header digest.
Preserve its facts as superseded with a content-free relocation receipt; genuinely
missing files are still retained. New keys must not count both old and new facts.
The replacement must cover the old captured offset and match its bounded head
and boundary fingerprints under a stable source stat; a matching header alone
does not retire a truncated or changed tail.

Range, task, parent-identity and transition queries accept canonical physical
page owners as well as logical-root owners. Ownership promotion and duplicate
selection use the checkpoint's physical identity, including fallback-key mirrors.
Normalized synchronization skips a proven page mirror only when its canonical
physical owner covers its captured prefix under the same guards. Existing mirror
facts are retained as superseded with a reason receipt, never deleted. This is
not authority to merge different physical branches or divergent historical facts.
Both the current mirror checkpoint and any older trusted generation must fit
within the canonical owner's captured extent and match one stable file snapshot.
Compare hashes at their own recorded offsets; small appends legitimately change
a whole-file head digest even though the earlier prefix is unchanged.

Resolve a baseline only through a caller-supplied frozen owned inventory. Never
interpret metadata as permission to discover or open an arbitrary path. Validate
the referenced header identity and captured file identity/size, a complete row
boundary and a preceding cumulative counter at the declared byte offset. Opening
counters may equal or advance the inherited counter; count only their positive
delta. A smaller opening counter is an attribution error, not a new zero origin.

Follow referenced physical prefixes recursively, including counter-free and
empty intermediate pages, with cycle detection and a 32-page chain ceiling.
Every contributing header must declare paginated history. Its outer ordinal is
the base's exclusive cutoff, or zero without a base. The declared byte endpoint
must end on a complete row with ordinal `cutoff - 1`; ordinals are not row counts.
A positive cutoff can select zero bytes from an intermediate page only when it
equals that page's metadata ordinal. An ordinal-zero reference is invalid.

Read at most 64 KiB of a candidate prefix and 256 KiB before its byte boundary,
with a 2 MiB total resolution budget across candidates and ancestors. Use unbuffered reads;
device/inode, size, mtime and ctime must remain stable across the read and final
path check. Growth before opening can preserve the declared captured prefix.
Any observed concurrent mutation, including growth, refuses that read snapshot:
without an independently pinned prior digest, growth cannot prove no rewrite.
Conflicting candidate baselines and unavailable/oversized evidence are named
coverage errors. Do not choose a candidate by newest mtime or token magnitude.

Resume restores the last non-null cumulative counter in the retained replay,
not a logical thread's global spent total. If a compaction separates the last
counter from the endpoint, replay may exclude that counter: fail with a named
unresolved-boundary condition rather than borrowing it. Unread local interiors
also cannot be skipped in favor of an ancestor's smaller counter.

Root-page metadata and the resolved counter survive a checkpoint even before its
first counter arrives. Later appends reuse that baseline without historical reads.
An external-base/replacement page contains post-boundary work, not inline parent
replay. An explicit empty logical-fork cutoff also has no imported replay. Preserve
the existing replay guards for original inline histories that can contain it.
Different physical IDs are not evidence of an invalid foreign fork.

Conversation reconstruction and financial history have different ownership:
reverting a conversation drops an abandoned suffix from replay, but must retain
its genuine historical consumption. Count the replacement page's new deltas from
its retained-prefix baseline without removing the old branch's spent usage.

Quota-only absent/null cumulative counters leave the baseline unchanged in both
ordinary and paginated sources. An explicit numeric zero counter is different;
do not reinterpret it as missing telemetry. Keep raw quota observations unchanged.

Capture prepares references once from the owned inventory and known metadata,
without attaching every source to every ordinary request. Prefix preparation and
reserved history resolution have an additional 8 MiB batch ceiling. Deferred
sources remain pending; failures rotate behind older pending work. Successful and
failed historical reads contribute to work accounting. Existing primary source
parse budgets remain separate and unchanged. Warm reusable/append paths do not
read inherited history.
Every permitted full-parse fallback reserves for a possible changed-header
reference, even when the cached header had no base. Deferred fallback paths do
not inherit that reservation because they cannot perform the history read.

## Alternatives And Consequences

Rejected dropping every first event, using the carried last-request object as
new usage, suppressing large values, modifying the fitted allowance value, and
globally resetting every parser cache. These discard real first responses or
conceal corrupt inputs without repairing lineage. Conservative coverage errors
may temporarily withhold a continued source rather than invent consumption.

The bounded reader proves the declared endpoint and counter, not every interior
row of a multi-gigabyte source. Missing required sources and unsupported replay
conditions remain visible coverage gaps. A missing base means an empty external
history, not authority to import an unrelated logical parent's counters.

Context-window-full events can synthesize a cumulative total with zero input and
output components; they are not necessarily billed responses. No magnitude-based
filter is introduced here. Universal response/billing reconstruction and usable
compaction companions remain outside this foundation's qualified claims.

## Remaining Qualification

Add bounded upgrade discovery and dependency-aware invalidation without global
multi-gigabyte reparsing. Audit affected continuations and the shared null-counter
defect, including mirror ownership, mixed writer versions and multiple-page overlap. Qualify repair on
a disposable snapshot, verify a private coherent backup and rollback, then apply
only approved facts/cache changes under source/revision checks. Raw logs and
official quota readings remain untouched. No current implementation is authority
to mutate a live ledger or claim corrected historical totals by itself.

Open qualification issue: **replica prefix authority**. A synthetic root consuming
100, an active page consuming 50 and a longer archived replica consuming 100 have
200 unique consumed tokens. Current storage-priority ownership selects 150 in
the cache and normalizes 250 when the longer replica cannot be skipped. No file
error is emitted. Resolve canonical ownership from verified captured-prefix
coverage, including partial/appended/missing copies, before release; never select
by token magnitude or discard the longer replica's genuine suffix. Existing
retirement guards prevent its loss but do not yet reconcile this overlap.

Regressions cover repeated/advanced counters, ordinary sessions, missing/history
conflicts, chunked checkpoints, quota-only rows before/after opening, continued
subagent forks, empty/multi-page/ancestor prefixes, explicit ordinal boundaries,
compaction barriers, spent reverted suffixes, source mutation, original/page
coexistence, normalized-ledger parity and history-free warm/append capture.

## Protocol Authority

Verified against OpenAI Codex `rust-v0.162.0-alpha.17.2`, source commit
`740e5af33c71225640e0c1c1555c514c2c93ab74`. This binds the reviewed protocol,
not provenance of an installed binary:

- [History position and metadata](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/protocol/src/protocol.rs#L3090-L3253).
- [Physical rollout filenames](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/rollout/src/rollout_file_name.rs#L10-L49).
- [Composed prefix lineage](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/thread-store/src/local/rollout_lineage.rs#L137-L201).
- [Replay counter restoration](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/session/mod.rs#L1643-L1678).
- [Compaction replay boundary](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/rollout/src/model_context.rs#L30-L58).
