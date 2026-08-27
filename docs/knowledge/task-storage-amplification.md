# Task Storage Amplification

## What We Observed

The largest Codex task trees are not necessarily the tasks with the most turns
or the most subagents. In the local corpus that motivated version 1.7.0, the
`TikTok mini games` family was disproportionately large because many files
contained repeated `compacted` history snapshots. Some snapshots also retained
inline media. Repetition of a large inherited payload across later rows and
descendants multiplied the physical JSONL bytes.

By comparison, `Plan ebook translation workflow` had many rounds and many
subagents but a much smaller storage footprint. Its activity was more
text-oriented and did not repeat the same amount of compacted payload. This is
why task count, turn count, and subagent count are useful context but poor
storage-cause metrics on their own.

## Diagnostic Model

Codex Usage calls a tree history-amplified only when a complete content scan
finds both:

- at least 1 GiB of compacted rows; and
- compacted rows representing at least 50% of the tree's logical JSONL bytes.

An inline-media warning additionally requires that same amplification result
and at least one bounded image, audio, video, or PDF marker inside compacted
history. Marker counts are clues, not decoded media sizes. A partial or missing
scan is reported as unknown and must never be treated as proof that a tree is
not amplified.

The **Active root history risk** flag is narrower: it identifies an active root
whose compacted history alone crosses the same absolute and relative threshold.
That is the clearest case for considering a fresh root task, because subsequent
work can continue inheriting the large root context.

## Operational Guidance

1. Use Task Storage to identify a large tree.
2. Run **Analyze** for that tree. The operation reads only the selected tree and
   retains guarded append checkpoints for later growth.
3. Review the compacted-history, inline-media, descendant concentration, and
   active-root flags together. Do not infer causality from total size alone.
4. Use **Fork in Codex** when conversational continuity is the priority. A fork
   is not a backup and does not guarantee lower inherited storage.
5. Create a fresh task with a concise handoff when reducing inherited context
   and future storage growth is the priority.
6. Verify the replacement before manually archiving or deleting the old task
   in Codex.

Codex Usage keeps this workflow diagnostic-only. Task creation, forking,
archiving, and deletion remain manual Codex-owned operations.

## Current Boundary

This knowledge describes evidence observed in Codex's local JSONL format as of
2026-08-08. Upstream formats can change. The schema 8 observer therefore uses
bounded classification with conservative fallbacks, and tests require complete
coverage before positive amplification labels are allowed.
