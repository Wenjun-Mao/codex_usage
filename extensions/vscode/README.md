# Codex Usage Companion

Codex Usage Companion is a standalone VS Code dashboard for a durable local
usage ledger, Task Storage, and Task Transfer. Each platform-specific VSIX
includes the matching collector for macOS Apple Silicon or Windows x64; Python,
uv, this repository, and the native app are not runtime requirements.

On activation, the extension authenticates an existing collector for the chosen
`CODEX_HOME` or starts one parent-bound collector of its own. The collector is
the only ledger writer, so stale descriptors and multiple VS Code windows do
not create duplicate writers.

![Codex Usage Companion dashboard](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/extension-usage-synthetic.png)

## Install

1. In the VS Code **Extensions** view, search for **Codex Usage Companion** and
   choose **Install**.
2. Open the Command Palette and run **Codex Usage: Set Up Collector**. Choose
   `CODEX_HOME`, a capture interval (or **Manual only**), and migrate a
   compatible legacy cache if one is offered.
3. Run **Codex Usage: Open Dashboard**.

No source checkout, native app, or local copy of this repository is needed.

## Supported Platforms

The extension ships separate platform VSIX packages for macOS 13 or later on
Apple Silicon and Windows 10 or later on x64. Intel macOS, Windows ARM64, and
Linux are not supported in 2.9.0.

## What You Can Do

- Open the ledger-backed Usage dashboard without rescanning task JSONLs.
- Run **Capture Usage** when you want current totals immediately.
- Set `CODEX_HOME`, scheduled capture or **Manual only**, and migrate compatible
  legacy usage caches entirely inside VS Code.
- Filter Usage by preset or inclusive custom local-calendar range and project,
  switch theme, review verified project transitions, keep the Agent Activity
  Daily Summary visible, expand its collapsed agent table when needed, and
  export complete CSV rows through the VS Code save dialog.
- Review global, model, and expandable project Image Generation activity without
  mixing it into language token or cost totals; incomplete history reports
  complete, pending, unavailable, and artifact counts.
- Inspect current Task Storage and explicitly analyze one selected task tree.
- Import, export, or review selected active tasks through Task Transfer.
- See last capture, pending work, stale-source warnings, and ledger revision in
  the status bar.

## Quick Start

1. Install the platform-specific Companion VSIX.
2. Run **Codex Usage: Set Up Collector** and choose a valid `CODEX_HOME`.
3. Choose a capture interval, or **Manual only** if you prefer explicit refreshes.
4. Run **Codex Usage: Open Dashboard** from the Command Palette.
5. Use **Codex Usage: Capture Usage** before manually deleting a task or whenever
   the scheduled interval is not fresh enough.

The Companion's collector is parent-bound: automatic capture stops when VS Code
closes. It continues while VS Code is open, even if the dashboard panel is
closed. Quota snapshots missed while VS Code is closed cannot always be
reconstructed later. The default interval is 15 minutes.

## Commands

| Command | Purpose |
| --- | --- |
| `Codex Usage: Open Dashboard` | Open the Usage or Task Storage report. |
| `Codex Usage: Capture Usage` | Scan changed task data into the durable ledger. |
| `Codex Usage: Reload Current View` | Re-query the Usage ledger or current Task Storage inventory without capturing task data. |
| `Codex Usage: Select Range` | Select a preset or inclusive custom local-calendar range. |
| `Codex Usage: Export Agent Activity CSV` | Save every selected agent-by-day row without re-reading task files. |
| `Codex Usage: Select Projects` | Filter Usage and Task Storage by project. |
| `Codex Usage: Select Theme` | Choose Auto, Day, or Night report styling. |
| `Codex Usage: Review Project Transitions` | Inspect verified repository switch points. |
| `Codex Usage: Show Usage` | Switch the dashboard to Usage. |
| `Codex Usage: Show Task Storage` | Switch the dashboard to Task Storage. |
| `Codex Usage: Task Transfer` | Open Import, Export, and status actions. |
| `Codex Usage: Choose Transfer Folder` | Choose the user-managed transfer folder. |
| `Codex Usage: Import Tasks` | Import selected tasks from one project. |
| `Codex Usage: Export Tasks` | Export selected active tasks from one project. |
| `Codex Usage: Review Transfer Status` | Compare selected local and transferred tasks. |
| `Codex Usage: Analyze Task Storage` | Analyze one selected task tree. |
| `Codex Usage: Set Up Collector` | Choose CODEX_HOME, interval or Manual only, and migrate legacy usage data. |
| `Codex Usage: Retire Legacy Background Service` | Explicitly hand off a previously registered Codex Usage service to the bundled collector while preserving the ledger. |

## Usage And Capture

Usage reports, Agent Activity, and its CSV export come entirely from
`CODEX_HOME/.codex-usage/usage-ledger.sqlite3`. Changing range, project filter,
theme, Agent Activity, or export does not reopen Codex task files. Custom ranges
require inclusive `YYYY-MM-DD` start and end dates in the collector's configured
timezone; malformed, reversed, and future dates are rejected. Agent Activity
shows daily totals immediately and at most 50 agents in a collapsed disclosure,
while CSV retains every selected agent-day row. Project Breakdown separates root
tasks and structured subagents, then stacks each role by model. Side-chat usage
remains under the parent root task where Codex does not store a durable role
discriminator.

Each role cell shows both tokens and API-equivalent dollars. Use the shared
**Compare by** control to change both Project Breakdown and Model Mix between
Tokens and API cost without regenerating the report. Models are shown by generation and product tier with
stable, distinct colors; the bounded visual set still prioritizes the models
responsible for the most tokens.

Project Economics adds a weighted all-project benchmark and expandable project
and model turn metrics from the same selected ledger rows. Distinct non-empty
project/task/turn identities define turns; blank turn IDs remain in totals and
coverage, while unpriced turns are excluded only from cost denominators.
Detailed Token Accounting is collapsed by default, and **Cache Write
(reported)** is copied from the ledger rather than inferred or reconstructed.

Image Generation reporting uses only durable image-event metadata. It keeps
operations, outputs, model evidence, exact values, and unpriced coverage
separate from language accounting; prompts, paths, bytes, and image contents
are not retained. Unknown or conflicting model evidence is shown as unpriced
rather than estimated.

Historical image recovery participates in startup, scheduled, and manual
captures. One capture reads no more than four 16 MiB rollout slices (64 MiB
total), serves new recent artifact owners first, and then rotates the least
recently served owners fairly. Missing or ambiguous owners remain visibly
unavailable without blocking a valid owner from using the bounded slice.

Pricing is bundled and effective-dated. GPT-6 Astra, Sol, and Luna are recognized
by exact model IDs, with cache-write and long-context API pricing. Sol and Luna
API rates begin September 22, 2026; earlier activity remains unpriced in USD.
Their Codex credit rates are not published, so credit coverage stays visibly
unpriced. See the [API pricing table](https://developers.openai.com/api/docs/pricing)
and [Codex rate card](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing).
Other credit estimates use published standard token rates and intentionally omit plan-specific or
Fast-mode multipliers because task records do not identify them reliably.

The collector normally checks every configured interval. Unchanged cycles may
inspect filesystem metadata but open zero JSONLs; ordinary growth reads only
guard windows and the new tail. **Capture Usage** coalesces with existing capture
work and resets the next interval after success. The reload icon only re-queries
the current view, so it does not scan task files or advance the ledger.

Deleted source tasks remain in historical totals only after their latest usage
was captured. Run **Capture Usage** before deleting. Codex Usage cannot restore a
deleted task.

## Task Storage

Task Storage reports current active and archived JSONL bytes by user-visible
root task tree and separates root files from structured descendants. It does not
follow the Usage date range. It shares the selected project filter and explicit
Auto, Day, or Night theme with Usage.

![Codex Usage Task Storage](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/extension-storage-synthetic.png)

Choose **Analyze** on a tree to scan only that tree for repeated compacted
history, inline-media evidence, descendant concentration, and active-root risk.
The operation is cancellable and does not invoke a model.
History amplification is labeled only after a complete analysis finds at least
1 GiB of compacted rows representing at least 50% of logical tree bytes;
otherwise the result remains **Not analyzed**, incomplete, or below threshold.

- Use **Fork in Codex** for conversational continuity; it is not a backup or a
  disk-reduction guarantee.
- Use a fresh task with a concise handoff when reducing inherited context is the
  priority.
- Verify the replacement before manually archiving or deleting the original.

Codex Usage does not create, fork, archive, restore, or delete tasks.

## Task Transfer

Task Transfer deliberately moves selected active task JSONLs through a folder
managed by OneDrive, Dropbox, iCloud Drive, Syncthing, a network drive, or a
similar filesystem provider. It never runs automatically.

### Export

1. Choose a transfer folder.
2. Choose one project.
3. Choose exact active tasks; no tasks are selected by default and search stays
   within the chosen project.
4. Export and wait for your filesystem provider to finish copying.

### Import

1. Ensure the matching project checkout already exists. Task Transfer does not
   clone repositories.
2. For Codex Desktop, add that checkout as a project and fully quit Desktop.
3. Choose the transfer folder, one project, exact tasks, and the local project
   folder.
4. Import, then start Codex Desktop or reload VS Code so Codex refreshes its
   task list.

Each Import or Export handles one project. Use the project Back action and
repeat for another project. Review Status compares state without copying.

The complete selected batch is validated first. Conflicts, changed files,
unsafe mappings, opposite-direction changes, running Desktop, ambiguous Desktop
projects, and assignment conflicts block the operation. Registration uses
targeted Codex `app-server` reads. It does not start a turn or consume tokens,
and no prompt is sent. Import atomically installs selected JSONLs but never
edits their content or writes Codex SQLite databases. Imported files remain in
the transfer folder, and only that folder path is retained as durable transfer
configuration.

## Settings

- `codexUsage.range`: dashboard range; default `30d`.
- `codexUsage.theme`: `auto`, `day`, or `night`.

Project selections are Companion UI state. Use **Set Up Collector** for
`CODEX_HOME`, capture interval, Manual only, and legacy-cache migration. A previously registered native background service can be retired
through the explicit Command Palette handoff. Keep the shared `.codex-usage`
directory when uninstalling the old app; **Reset Local Data** is not a handoff
step.

## Privacy

The companion connects only to the authenticated collector on `127.0.0.1`.
Its webview never receives the bearer token. It has no telemetry and does not
upload task content. See the full [privacy policy](https://github.com/Wenjun-Mao/codex_usage/blob/main/PRIVACY.md).

For support, open a [GitHub issue](https://github.com/Wenjun-Mao/codex_usage/issues)
and include the extension version, operating system, collector status,
and redacted Codex Usage output. Never attach raw task JSONLs publicly.

## Plan Allowance

The account-wide Plan Allowance section shows active quota buckets and reset
metadata, plus the **Observed API-equivalent value of full allowance** when a
window has a valid priced fit. Fits need at least 10 percentage points; stronger
confidence also requires completed windows and the documented coverage and
sensitivity gates. If the newest window is not yet priceable, the headline can
show a dated **Previous window** estimate from the same limit, plan, and duration
series. It never borrows across series. Collapsed diagnostics list recent valid
priced windows, including current and provisional fits. Project and date filters
do not change this account-wide section.

Captures use official Codex App Server metadata reads without a model turn.
Unavailable probes do not fail ordinary capture. Historical recovery checks
registered sources newest-first with bounded endpoint reads, up to 8 MiB per
capture, and resumes automatically. Recovery is partial, with provenance and
coverage disclosed. Upgrades back up and preserve existing usage and checkpoints.
Report navigation reads only the ledger. No account identity, authentication,
prompts, or content is retained by allowance collection.

This is a local workload-specific API-equivalent estimate, not cash value or a
contractual entitlement. Other-device usage, missing history, model mix, and
pricing can affect it. Lifetime account tokens are coverage diagnostics only.
