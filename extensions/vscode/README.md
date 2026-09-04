# Codex Usage Companion

Codex Usage Companion is a standalone VS Code dashboard for a durable local
usage ledger, Task Storage, and Task Transfer. Each platform-specific VSIX
includes the matching collector for macOS Apple Silicon or Windows x64; Python,
uv, this repository, and the native app are not runtime requirements.

On activation, the extension authenticates an existing collector for the chosen
`CODEX_HOME` or starts one parent-bound collector of its own. The collector is
the only ledger writer, so stale descriptors and multiple VS Code windows do
not create duplicate writers.

![Codex Usage native dashboard](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/native-usage-synthetic.png)

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
Linux are not supported in the 2.x release line. The optional native app is an
unsigned, self-contained native app preview with its own background collector
and full native UI, but it is not required for Companion commands. Its CI
artifacts include SHA-256 integrity metadata; the operating system may display
an unidentified-developer or unknown-publisher warning.

## What You Can Do

- Open the ledger-backed Usage dashboard without rescanning task JSONLs.
- Run **Capture Usage** when you want current totals immediately.
- Set `CODEX_HOME`, scheduled capture or **Manual only**, and migrate compatible
  legacy usage caches entirely inside VS Code.
- Filter Usage by range and project, switch theme, and review verified project
  transitions.
- Inspect current Task Storage and explicitly analyze one selected task tree.
- Import, export, or review selected active tasks through Task Transfer.
- See last capture, pending work, stale-source warnings, and ledger revision in
  the status bar.

The native app remains the home for background capture outside VS Code,
installer, and update workflows. It is optional and is not required for any
Companion command.

## Quick Start

1. Install the platform-specific Companion VSIX.
2. Run **Codex Usage: Set Up Collector** and choose a valid `CODEX_HOME`.
3. Choose a capture interval, or **Manual only** if you prefer explicit refreshes.
4. Run **Codex Usage: Open Dashboard** from the Command Palette.
5. Use **Codex Usage: Capture Usage** before manually deleting a task or whenever
   the scheduled interval is not fresh enough.

The Companion's collector is parent-bound: automatic capture stops when VS Code
closes. It continues while VS Code is open, even if the dashboard panel is
closed. Automatic capture outside VS Code requires the optional native app to
have installed its separate background collector. The default interval is 15
minutes.

## Commands

| Command | Purpose |
| --- | --- |
| `Codex Usage: Open Dashboard` | Open the Usage or Task Storage report. |
| `Codex Usage: Capture Usage` | Scan changed task data into the durable ledger. |
| `Codex Usage: Reload Current View` | Re-query the Usage ledger or current Task Storage inventory without capturing task data. |
| `Codex Usage: Select Range` | Select Today, Yesterday, 7d, 30d, Month, or All. |
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
| `Codex Usage: Open Native App` | Open an installed native preview, or its build page when absent. |

## Usage And Capture

Usage reports come entirely from
`CODEX_HOME/.codex-usage/usage-ledger.sqlite3`. Changing range, project filter,
or theme does not reopen Codex task files. Project Breakdown separates root
tasks and structured subagents, then stacks each role by model. Side-chat usage
remains under the parent root task where Codex does not store a durable role
discriminator.

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

![Codex Usage Task Storage](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/native-storage-synthetic.png)

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
`CODEX_HOME`, capture interval, Manual only, and legacy-cache migration. The
optional native app separately owns its own background registration and update
settings.

## Privacy

The companion connects only to the authenticated collector on `127.0.0.1`.
Its webview never receives the bearer token. It has no telemetry and does not
upload task content. Optional GitHub update checks are owned by the native app.
See the full [privacy policy](https://github.com/Wenjun-Mao/codex_usage/blob/main/PRIVACY.md).

For support, open a [GitHub issue](https://github.com/Wenjun-Mao/codex_usage/issues)
and include the app and companion versions, operating system, collector status,
and redacted Codex Usage output. Never attach raw task JSONLs publicly.
