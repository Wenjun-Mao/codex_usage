# Codex Usage Dashboard

Stable Windows x64 and macOS Apple Silicon VS Code extension for local-first Codex usage reporting: view project activity, token usage, Codex credits, and API-equivalent cost estimates from local Codex session JSONL logs. Project Breakdown separates each project into user-visible root tasks and structured subagents, then stacks each role by model.

## Features

- Two focused views keep date-filtered **Usage** separate from current **Task Storage**. Projects and theme apply to both; the date range applies only to Usage.
- Task Storage shows current local JSONL usage by user-visible root task tree, diagnoses repeated compacted-history and inline-media amplification on demand, and prepares guarded rollovers through a new verified backup.
- Project Breakdown separates each project into user-visible root tasks and structured subagents, then stacks each role by model.
- Model Mix uses shared model colors across the report. Model Details remains exact while crowded charts group models after the largest seven into visual-only `Other`.
- Shows total tokens, API-equivalent USD, Codex credits, cache hit share, and daily/hourly views.
- Uses checked-in effective-dated pricing tables. No live pricing fetch is performed.
- Adds optional cross-computer Task Transfer through a user-provided folder; token reporting works without it.
- Opens a local dashboard from Codex session JSONL logs.
- Auto-discovers the default active and archived Codex session directories.
- Supports quick range switching: today, yesterday, 7d, 30d, month, all.
- Supports multi-project filtering from detected project keys.
- Supports auto/day/night dashboard theme switching.
- Detects high-confidence project transitions and can split dashboard usage after verified local repository changes.

![Synthetic Codex Usage Dashboard screenshot](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/dashboard-synthetic.png)

## Supported Platforms

The stable Marketplace release supports Windows x64 and macOS Apple Silicon only. The installed extension bundles `codex-usage.exe` on Windows and `codex-usage` on macOS, and does not require Python, `uv`, or this repository at runtime. The release workflow runs both native packaged version-3 Task Transfer smoke gates, one on Windows x64 and one on macOS Apple Silicon, and requires them to pass before publication. Additional packaged gates cover report and cache behavior, verified task backups, and storage analysis, including zero-byte warm-analysis reuse; they must also pass. Intel macOS and Windows ARM64 are not supported targets in this release. Linux packaging is a follow-up and is not a supported target in this release.

## Commands

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Select Theme`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Task Transfer`
- `Codex Usage: Choose Transfer Folder`
- `Codex Usage: Import Tasks`
- `Codex Usage: Export Tasks`
- `Codex Usage: Review Transfer Status`
- `Codex Usage: Back Up Task`
- `Codex Usage: Analyze Task Storage`
- `Codex Usage: Prepare Task Rollover`
- `Codex Usage: Open Transfer Folder`
- `Codex Usage: Open Settings`

## Settings

- `codexUsage.range`: dashboard range, default `30d`.
- `codexUsage.theme`: `auto`, `day`, or `night`. Auto follows your active VS Code theme.
- `codexUsage.projectTransitions.autoDetect`: automatically split usage after high-confidence local repository transitions.

Project filtering is managed with `Codex Usage: Select Projects` and is stored as extension UI state, not as a user setting.
The selected Usage or Task Storage view is remembered only for the current extension session. Switching views does not regenerate the report.
Task Transfer remembers only the transfer-folder path as extension UI state. Task selections and project mappings are never saved.

## Task Transfer

Task Transfer deliberately moves selected active Codex tasks between computers through a folder managed by OneDrive, Dropbox, iCloud Drive, Syncthing, a network drive, or another filesystem provider. It is optional: token reporting works without Task Transfer, and the extension never transfers tasks in the background.

Codex's built-in handoff can fail on a very large task. Task Transfer preserves the task as a full JSONL without summarizing or repackaging its context, so the same long-running task can continue on another computer.

1. On the source computer, run **Export Tasks**, choose the project, and select the active tasks to transfer.
2. Wait for the filesystem provider to finish copying the transfer folder.
3. Clone or copy the corresponding project checkout to the destination computer if it is not already there.
4. When using only the Codex IDE extension, open that checkout in VS Code.
5. Run **Import Tasks**, choose the project, and accept an automatic project match or choose a validated local folder.
6. After successful registration, reload VS Code or open/restart Codex so the imported tasks
   appear. In the official Codex VS Code extension, reloading VS Code refreshes a cached task list.

The Codex desktop app is not required. An IDE-only workflow uses open VS Code workspace folders as destination candidates. Git-backed projects are matched and validated by normalized Git origin; a chosen checkout with the wrong origin is rejected. For a non-Git project, the extension shows the source and destination and asks for confirmation because the mapping cannot be verified automatically. Task Transfer does not clone repositories, so the destination checkout must already exist.

Each Import or Export handles one Codex project. First choose one project, then choose one or more eligible tasks from that project. No tasks are selected by default. Search on the task screen is limited to the chosen project. Use Back to discard the current task choices and choose a different project. Repeat the operation to transfer tasks from another project. The transfer folder can retain tasks from many projects across separate operations. Review Transfer Status remains cross-project and does not copy files. Neither task selections nor project mappings are saved. Imported tasks remain in the transfer folder, and changing or forgetting the remembered folder does not delete any task files.

The extension checks the complete selected batch before copying anything. Conflicts, malformed folder structures, changed source files, unsafe mappings, and tasks that need the opposite direction block the whole operation. Existing local tasks keep their current checkout path. Task Transfer does not copy Codex auth, settings, caches, logs, archived tasks, or SQLite databases.

After certified task files are copied during Import, Codex Usage asks an installed official Codex runtime to register the selected tasks through targeted `app-server` task-read requests. Registration sends targeted reads only: it does not invoke a model, send a prompt, or start a turn. Codex Usage never writes Codex SQLite or private project registries directly; Codex owns the resulting state repair. If registration fails, the certified imported files remain safe in place, and re-running Import retries registration for the selected tasks. After successful registration, open or restart Codex, or reload VS Code when using the official Codex VS Code extension, to refresh a cached task list.

On supported Windows x64 and macOS Apple Silicon installations, official runtime discovery checks the official Codex VS Code extension, the native Codex desktop app, and `PATH`; the desktop app is not required when another official runtime is available. The packaged Codex Usage VSIX is limited to Windows x64 and macOS Apple Silicon.

The current transfer-folder layout is:

```text
<transfer-folder>/
  sync-index.json
  tasks/
    <portable-task-filename>.jsonl
```

Valid version-2 folders migrate automatically to this version-3 layout before Import, Export, or Review. The **Task Transfer** menu lets you choose, change, open, or forget the folder. Only that folder path is remembered.

### Archive/Delete Accounting

Archived Codex tasks are included in usage totals. Deleted or otherwise missing tasks are retained in historical totals after the local cache has parsed them once. The dashboard header shows archived and retained missing file counts when applicable.

## Project Transitions

Automatic project transition detection uses read-only evidence from local Codex session JSONL files and, when present, project paths and timestamps from the local Codex database. The extension does not upload this data, make network calls for transition detection, mutate SQLite, or include SQLite databases in Task Transfer.

The dashboard transition table shows source, target, effective timestamp, and confidence. Use `Codex Usage: Review Project Transitions` for detailed evidence and Task IDs.

## Install

Windows x64:

```powershell
code --install-extension output\releases\codex-usage-dashboard-win32-x64.vsix --force
```

macOS Apple Silicon:

```bash
code --install-extension output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```

After installation, run `Codex Usage: Open Dashboard` from the command palette.

## First Run And Cache

The first `1.7.0` report builds the disposable schema 8 cache once. Later reports query only the selected range from local SQLite, value each retained record once, and reuse that valuation throughout the report. Schema 8 also retains guarded Task Storage content diagnostics whenever the usage parser has already read a file. The extension passes an internal cache folder to the bundled Python CLI and keeps it under VS Code global extension storage. The cache is local only and pricing still uses checked-in effective-dated rates. The toolbar displays `Loaded in X.X seconds` for the report currently shown. No cache setting is exposed in VS Code Settings; deleting the extension storage folder simply causes the cache to rebuild.

Unchanged refreshes open no session JSONLs. A growing active JSONL can resume from an atomically committed parser checkpoint after its path, OS file identity, task ID, head digest, and 64 KiB old-boundary digest are verified, so an ordinary append reads only fixed guard windows plus the new tail. Replacement, truncation, same-size modification, unavailable identity, digest mismatch, invalid state, or an archived-file change triggers a safe full parse. The parser reads only through the size captured during inventory and defers an incomplete final row from its starting offset.

At most four read-only workers use buffered binary I/O to parse groups of eight files in descending unread-byte order. SQLite remains in the parent process and atomically commits records, metadata, candidates, fingerprints, and checkpoints; a failure retains the prior generation. Task Transfer metadata discovery stops as soon as it reads valid `session_meta`. Range-aware cache queries use UTC-microsecond timestamps, refresh coordination retains only the latest request while an active process finishes, and cache diagnostics in the timing sidecar and VS Code Output channel distinguish full parses, append parses, append fallbacks, and source bytes read.

## Task Storage

The dashboard's separate **Task Storage** view reports the current local JSONL corpus without following the Usage date range. It groups physical files into user-visible root task trees, separates root-task bytes from nested structured-descendant bytes, includes active and archived files, and follows the selected project filter. The report shows the largest trees as horizontal bars and lists every tree with logical bytes, file counts, storage state, share, analysis coverage, and diagnostic flags. Transparent badges mark root size at 1 GiB and total tree size at 10 GiB.

Codex guardian approval logs remain visible as structured descendants of their explicit owning task. Their bytes and verified backups stay with that tree, while recorded `codex-auto-review` tokens remain under **Subagents** in Usage; the extension neither hides them nor presents them as user-created roots.

![Synthetic Task Storage screenshot](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/task-storage-synthetic.png)

The purpose is visibility before starting a fresh root task. These measurements are dated audit snapshots, not expected installation sizes. The 2026-08-07 audit measured 196.08 GiB across 2,525 files, including 187.63 GiB in structured descendants; a 2026-08-08 follow-up had reached 383.00 GiB across 2,563 files, including 372.60 GiB in structured descendants. Size alone does not explain that growth. Choose **Analyze** on one task tree to measure repeated compacted-history rows, inline-media markers, large descendants, and active-root history risk. The selected-tree scan uses at most four local read-only workers; it neither invokes a model nor scans unrelated trees.

A positive **History amplification** label requires complete analysis, at least 1 GiB of compacted rows, and compacted history representing at least 50% of the tree. **Inline media** additionally requires media markers inside that amplified history. `not analyzed` or `partial` remains visibly unknown rather than becoming a false negative. Marker counts are diagnostic clues, not decoded media size or reclaimable-space estimates.

Codex documentation describes side chats as ephemeral forks. In the observed local format, the side-chat turn is stored in the parent root JSONL without a separate task, file, or durable discriminator. Its bytes and token usage remain under **Root task**, and the report says so instead of inventing a heuristic third role. A future split requires reliable upstream metadata and will not retroactively guess older records.

### Verified Task Backups

Use **Back Up** on a Task Storage row or run **Codex Usage: Back Up Task** to back up exactly one task tree. The backup preserves every physical JSONL currently present under that root, including structured descendants such as guardian approval logs, active and archived copies, duplicates, and side-chat content already embedded in the root JSONL.

The `.codex-task-backup` format is a streaming PAX tar compressed as exactly one zstd frame with a strict format-v1 manifest. It includes canonical metadata, per-file SHA-256 values, bounded selected session-index entries, and a final whole-archive SHA-256. **Maximum** uses zstd 19 for smaller, slower archives; **Balanced** uses zstd 9 for faster, larger archives.

Source identity is checked before, during, and after the copy, and the complete selected tree is inventoried again before publication. The archive is written to a sibling partial file, fully reread and verified, then atomically published. Existing backups remain in place unless verified replacement succeeds. Cancellation or failure leaves no reported final archive; a forced process termination can leave an unreported hidden sibling partial, which is never treated as the requested backup. Transient metadata reads are retried, and any still-unresolved corpus file prevents a recovery-ready claim because its parent tree cannot be proven. Missing roots, relationship cycles, or metadata diagnostics therefore produce a warning-bearing salvage archive that may be integrity-verified but is not recovery-ready.

Backups can contain prompts and source code. They are compressed but not encrypted, stay local, and use neither telemetry nor the network. This feature does not restore or delete Codex tasks and does not free storage. Safe restore and deletion are follow-up work; future restore code is not promised compatibility beyond strict format-version rejection.

### Prepare Rollover

For a completely analyzed tree that is large or history-amplified and recovery-ready, choose **Prepare Rollover**. The extension first creates a new verified Maximum or Balanced backup at a new path. After verification, it copies a text-only starter prompt to the clipboard and writes a checklist to the Codex Usage Output channel.

Codex Usage does not create, archive, restore, or delete Codex tasks. Create a fresh root task yourself in the same project, verify its context, and only then archive or delete the old task in Codex. Preparing rollover establishes a recovery point and continuity material; it does not reduce disk usage by itself.

## Privacy

The extension reads local Codex session JSONL files and writes local HTML reports and disposable SQLite caches under VS Code extension storage. When requested, it also writes Task Transfer files and verified backups to folders the user selects. Automatic project transition detection can read local Codex project paths and timestamps as read-only evidence. The extension does not upload session logs, include telemetry, fetch live pricing, or include or mutate SQLite databases in Task Transfer.

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. See the repository `PRIVACY.md` for details.

## Pricing And Fast Mode Notes

API-equivalent USD and Codex credit estimates are calculated from checked-in effective-dated pricing tables. The extension does not fetch live pricing, does not know your subscription price, and does not convert Codex credits to dollars. If a newly released Codex model appears before checked-in rates are added, the dashboard keeps its tokens visible and marks cost/credits as partial rather than guessing from another model.

GPT-5.6 Sol, Terra, and Luna use official API rates for usage recorded from June 26, 2026 onward. Their Codex credit estimates start July 9, 2026 and remain flat across context length. Reasoning effort such as `ultra` remains separate metadata and does not change the per-token model rate.

The original Terra and Luna API rates apply through July 30, 2026. Reduced Terra and Luna API rates apply from July 31, 2026; earlier usage keeps the original effective-dated rates. GPT-5.6 Sol API pricing and all three models' Codex credit rates are unchanged.

The official `gpt-5.6` model alias is priced as GPT-5.6 Sol. Other variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names remain visible but unpriced unless they exactly match a checked-in model id or explicit alias.

API-equivalent USD figures are estimates, not actual API or Codex billing. For GPT-5.6, standard cache-write rates per 1M tokens are: Sol $6.25, Terra $2.50, Luna $0.25; cache read (cached input) and ordinary input remain distinct categories. Exactly 272,000 input tokens is short-context pricing. More than 272,000 input tokens, including 272,001, prices the full retained request event at long-context API rates. Long-context rates per 1M tokens are: Sol ordinary input $10, cache read (cached input) $1, cache write $12.50, output $45; Terra ordinary input $4, cache read (cached input) $0.40, cache write $5, output $18; Luna ordinary input $0.40, cache read (cached input) $0.04, cache write $0.50, output $1.80. Codex credits do not use long-context or API cache-write categories; cache writes use the ordinary input credit rate.

The parser reads cumulative token records but reports only retained positive deltas. A local audit of GPT-5.6 Sol sessions found retained positive deltas matched request-level `last_token_usage`, so pricing is per retained event and cumulative session totals cannot trigger long-context pricing.

For GPT-5.6 and later API models, local Codex logs expose `cache_write_input_tokens`. API-equivalent USD prices those explicit cache writes at 1.25 times the ordinary input rate, including the long-context multiplier when applicable; remaining ordinary input uses the standard input rate. Codex credits have no separate cache-write category, so cache writes use the published ordinary input credit rate. Cache-contract changes reparse available source JSONL files, but retained records whose source JSONL is missing cannot gain newly observed token evidence; reports disclose that limitation.

Codex fast mode is counted through the token usage that Codex records. At the moment, Codex session JSONL files do not expose a durable per-turn fast-mode marker or exact charged-credit field, so the dashboard cannot label GPT-5.5 fast-mode turns separately from regular GPT-5.5 turns.

## Troubleshooting

### Imported files exist but tasks are not visible

1. Confirm an official Codex runtime is installed on the destination computer.
2. Check the Codex Usage output for a post-import registration failure.
3. Run **Import Tasks** again for the same project and task subset to retry registration.
4. Open or restart Codex, or reload VS Code when using the official Codex VS Code extension.

- If no usage appears, confirm Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
- If project filtering shows no choices, switch the range to `all` and run `Codex Usage: Select Projects` again.
- If a project split looks surprising, run `Codex Usage: Review Project Transitions` to inspect the evidence, or disable `codexUsage.projectTransitions.autoDetect`.
- If the dashboard theme is not what you expect, run `Codex Usage: Select Theme` and choose `auto`, `day`, or `night`.
- If the dashboard says no sessions were found, check the detected sessions path and file permissions.
- If pricing looks stale, check the report header for the checked-in pricing table date.

## Development

Windows x64 packaging is CI-only. The GitHub Actions Windows job runs the extension tests, builds `codex-usage.exe`, and executes the native packaged report/cache, version-3 Task Transfer, verified-backup, and storage-analysis smoke gates before publication.

macOS Apple Silicon on macOS/bash from `extensions/vscode`:

```bash
npm install
npm run build
npm test
npm run package:vsix:mac
```

For the shortest loop, open this folder as the VS Code workspace and press F5. The included launch configuration starts an Extension Development Host.
