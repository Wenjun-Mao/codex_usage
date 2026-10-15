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

## Staged Semantic Repairs

A rebuild tracks its discovered physical key across slices while retaining the
original live source key as the installation precondition. Staging may advance
without changing report authority. Do not mistake the old logical slot for the
staged checkpoint key or restart the staged capture on every slice.
Use versioned staging paths: retain older unbound parser stages without adopting
their checkpoints. Persist the captured owner's fingerprint and first qualified
header independently of parser rows. After interruption, bind an already-saved
checkpoint's header before further parsing or schema handling. Check provenance
before destructive reset; malformed or unbound evidence cannot authorize reuse.
Schema resets and failed retries cannot silently rebind that authority.
Refuse changed logical identity or a cross-slice
header/lineage change, including a downgrade to ordinary-session parsing.

Install a complete stage, its source-key change, normalized replacement, revision
and dependent invalidation in one transaction. Readers observe either authority,
never a parser/ledger half-swap. A complete retained checkpoint does not qualify
an errored stage. Recheck the live origin and attached stage, and require trusted
replacement bindings after normalization before retirement can commit.
Even a byte-identical, same-row-count semantic
repair creates a new normalized generation: append heuristics cannot prove that
the old values implement the corrected accounting contract. Retain old normalized
events as superseded with a content-free `source-rebuild` receipt binding the
captured origin, header contract and history-boundary digests. Copy all
source-scoped workset facts, including quota cache; do not alter captured account
readings or credit observations.

Refuse an occupied destination with retained facts or a shorter paginated stage
that would discard a retained suffix. Check the source snapshot before verification
and before commit. Failure rolls back the authority swap and retains staging for
retry. This contract does not authorize replacing unresolved sibling replicas,
skip full repair qualification, or substitute for mixed-writer quiescence and the
fresh source/revision checks required for live application.

## Remaining Qualification

Add bounded upgrade discovery and dependency-aware invalidation without global
multi-gigabyte reparsing. Audit affected continuations and the shared null-counter
defect, including mirror ownership, mixed writer versions and multiple-page overlap. Qualify repair on
a disposable snapshot, verify a private coherent backup and rollback, then apply
only approved facts/cache changes under source/revision checks. Raw logs and
official quota readings remain untouched. No current implementation is authority
to mutate a live ledger or claim corrected historical totals by itself.

**Replica prefix authority:** a synthetic root consuming 100, an active page
consuming 50 and a longer archived replica consuming 100 have 200 unique consumed
tokens. Storage-priority ownership incorrectly selected 150 in the cache and
normalized 250, without a coverage error. Paginated replicas now select one
longest compatible physical source *before* scheduling parsing. Prove every
available shorter copy and retained accounting-valid prefix against that source
using the established bounded head/boundary guards on a stable frozen snapshot;
this is not a claim of full interior-byte equality. Never select by token magnitude.

Rebind the complete checkpoint only after proof; adopt a larger compatible
cached generation whole rather than merging independent response indexes. All
header/proof reads share the existing 8 MiB extra-history budget. An unchanged
member/stat set reuses a content-free proof receipt without reopening headers or
prefixes, including after partial checkpoint advancement. Keep the full raw
inventory separately available to inherited-history resolution. Missing a longer
canonical copy retains its captured facts and exposes a named coverage gap;
divergent copies do not become independent consumption.

Before adopting/removing fallback keys, retain a physical-alias receipt containing
the covered parser and trusted-generation prefixes. Cache selection excludes
proven mirrors. Normalized retirement requires an exact trusted canonical
checkpoint covering those prefixes and the same proved target snapshot; retain
old facts plus the retirement receipt, not a second charge. Existing same-path
relocation proof remains valid. Ordinary unclassified legacy sources keep their
existing ownership path; a filename alone is not paginated-header authority.
Pending alias prefixes survive removal of the donor's cache row. Every changed
owner snapshot must prove and renew those obligations through append/handoff
until normalized retirement completes; capture and normalization need not be
adjacent. Do not relax exact snapshot matching to accommodate a delayed sync.

[ADR 0065](0065-retained-accounting-authority.md) handles retained accounting when
no available raw copy covers the longer capture. It proves stored-fact dominance
or withholds an unresolved family; it never supplies missing byte-prefix proof,
rebinds checkpoints, or claims completeness against lost raw data. Upgrade,
mixed-writer, disposable/live-repair and release qualification remain separate.

[ADR 0067](0067-bounded-accounting-upgrade-discovery.md) discovers weak historical
checkpoints before ownership changes, reserves their logical slots and bounds
staged retries. Discovery is not repair authority or missing-source rebinding;
mixed-writer safety and private repair qualification remain separate work.

## Dependent Baseline Invalidation

An aggregate baseline digest cannot identify which unchanged continuations used
a replaced ancestor. The bounded resolver now retains every physical boundary
in its validated chain, including ancestors whose intermediate page has never
been captured. Checkpoints serialize these content-free references. Resume
authority requires a valid, unique chain whose opening matches root metadata;
older evidence remains readable but must undergo bounded upgrade discovery.

Replacing a trusted normalized source generation, or installing a staged repair,
invalidates captured descendants in the same accounting transaction. Use the
previous normalized physical path when ownership changes, not the new occupant's
identity. Ordinary guarded appends do not invalidate frozen ancestor prefixes.
This does not add full-interior rewrite detection beyond the existing bounded
source proofs. No raw history is opened to discover dependent captures.

Retain checkpoints and accounting facts, mark coverage stale and advance a
per-source invalidation epoch with a durable pending-repair marker. That marker
gates request planning, append commits, normalization and replica/ownership
handoffs independently of replaceable diagnostic strings. Waiting claimants name
their canonical blocker so unchanged captures do not reparse them. Malformed
dependency entries preserve valid edges and are explicitly quarantined, rather
than aborting unrelated replacement. A quarantine remains pending until repair.

Only a complete authorized staged install clears pending authority. The epoch
participates in its captured-origin fingerprint and staging identity. An ancestor
replacement between child slices starts a new epoch-bound stage, retaining the
obsolete stage rather than adopting it. The `accounting-v2` namespace refuses old
pre-dependency stages. Marker/epoch movement follows source-key changes atomically.
Private repair qualification must include obsolete-stage storage and cleanup in
its maintenance/rollback lifecycle; no automatic deletion is introduced here.
Captured quota observations remain untouched; revision-pinned allowance, economics,
credit and HTML consumers observe either the old transaction or its invalidation.
Regressions cover transitive/uncaptured ancestors, append/replica escape attempts,
malformed references, obsolete stages, rollback and cache/direct-parser parity.

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
