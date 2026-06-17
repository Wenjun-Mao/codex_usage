# Debugging And Incident Notes

This page captures the bugs and surprises that taught the most. The goal is not blame. The goal is to remember the shape of the failure, the evidence that mattered, and the durable fix.

Future me: a bug is often a missing concept. When the fix feels awkward, ask what the model failed to represent.

## Duplicate Project Rows

Symptom: the dashboard showed two rows with the same project label. One came from a git repository URL and one came from a path-only session.

Root cause: project grouping had a weak identity model. It could fall back to `cwd`, but it did not always resolve missing git metadata from the local repo. The display label made the rows look identical even though the keys were different.

Durable fix: add canonical project identity. Prefer `git.repository_url`, resolve `.git/config` from `cwd` when possible, normalize remote URLs, and keep path aliases for old filters.

Lesson: labels are presentation, not identity.

## Forked Threads Counted As New Usage

Symptom: after forking or continuing conversations, old parent usage could appear as usage for the current day.

Root cause: fork files can replay inherited parent context before recording new work. Treating the first cumulative token snapshot as fresh usage overcounted.

Durable fix: detect forked root session replay and skip the inherited first root snapshot when there is no prior baseline. Keep positive-delta accounting for actual later usage.

Lesson: event logs can contain replayed history. "Present in the file" does not always mean "newly consumed now."

## Repo Rename And Project Transition

Symptom: a conversation started under one repo name and continued after the repo was renamed and recloned. The dashboard needed to split usage at the transition while still showing the projects as related.

Root cause: canonical identity alone cannot explain time-varying project context inside one conversation.

Durable fix: add automatic project transition detection using timestamped evidence from JSONL and read-only local Codex SQLite thread metadata where available. Apply transitions after parsing and before reporting.

Lesson: identity and history are different concepts. A stable key answers "what is this?" A transition answers "when did this become something else?"

## Slow Range Switching

Symptom: switching date ranges in the dashboard could take more than ten seconds.

Root cause: every refresh reparsed local Codex files. The extension was treating a report interaction like a full data ingestion job.

Durable fix: add a local SQLite cache for parsed usage rows, file summaries, and transition results. Reuse unchanged files and show first-run initialization copy.

Lesson: the user should pay the full scan cost once, not on every UI gesture.

## Deleted Or Archived Conversations

Symptom: archiving and deleting conversations raised the question of whether historical usage should disappear from reports.

Root cause: the product had not named whether usage was "current visible Codex conversations" or "historical usage observed by this tool."

Durable fix: treat usage as historical accounting. Include archived sessions. Retain parsed missing-file usage after the cache has seen it once. Show retained missing-file counts for transparency.

Lesson: cache semantics are product semantics. Decide what a missing source file means before coding the cache behavior.

## Sync File Replace Failure On Windows

Symptom: sync produced repeated Windows permission errors while importing a session file.

Root cause: import attempted to replace a local session file even when the local and remote content were already byte-for-byte identical. Windows file locks made the unnecessary replace fail repeatedly.

Durable fix: make import idempotent. If hashes match, skip file replacement and only merge index metadata as needed.

Lesson: avoid writes when no state change is needed. Idempotence is a reliability feature.

## Noisy Sync Popups

Symptom: sync failures could keep popping notifications even after the user turned sync off or while an old extension version was draining queued work.

Root cause: background automation used visible notifications too aggressively and did not clearly separate normal status, waiting, retry, and action-needed states.

Durable fix: move normal sync state to the status bar and output channel. Add debounce, cooldown, failure backoff, and action-needed notifications only for manual sync or conflicts/issues that require user attention.

Lesson: background features should be quiet by default. A repeated popup is a UX failure, even when the error is real.

## Thread-First Sync UX Confusion

Symptom: the sync picker listed many "threads," but the user thought in terms of projects. The difference between project and conversation was unclear.

Root cause: the implementation model leaked into the UI. Sync identity is conversation/thread id, but user selection starts from project context.

Durable fix: make sync setup project-first, then conversation selection. Add rough size estimates per project so cloud storage impact is understandable.

Lesson: expose the user's mental model first. Keep internal identity visible only when it helps.

## Heatmap Hover Performance And Layout Polish

Symptom: hover details felt slower and less polished than the built-in Codex usage UI. Text wrapped poorly and the heatmap sizing felt inconsistent.

Root cause: the dashboard was technically correct before it was interaction-polished.

Durable fix: improve tooltip markup, split tooltip text into two lines, use CSS-only hover behavior, remove excessive amber intensity, and tune compact centered heatmap sizing.

Lesson: visualization quality is not only the chart type. It is also hover latency, label fit, color restraint, and rhythm with surrounding sections.

## Fast Mode Accounting

Symptom: Codex fast mode claimed increased usage, but the plugin could not label fast-mode turns separately.

Root cause: recorded JSONL usage contains token counts, but does not expose a durable per-turn fast-mode marker or exact charged-credit multiplier.

Durable response: count the recorded token usage honestly and document the limitation. Do not invent a separate fast-mode label without source data.

Lesson: best-effort analytics must distinguish observed facts from inferred labels.

