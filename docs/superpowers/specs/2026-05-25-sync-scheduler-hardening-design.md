# Sync Scheduler Hardening Design

## Purpose

Make experimental Codex sync feel predictable and calm. The extension should sync selected conversations often enough to be useful across machines, but it should not start overlapping syncs, retry rapidly after failures, or keep showing background warnings after the user disables sync.

This design covers the VS Code extension scheduler only. The Python CLI remains the sync engine and the existing `sync status`, `sync import`, and `sync export` command sequence stays unchanged.

## Current Behavior

The extension currently starts auto sync in three places:

- Extension activation calls `syncOnFocus`.
- VS Code focus changes call `syncOnFocus`.
- Session JSONL create/change events schedule `syncNow(context, "watch")` after a 2-second debounce.

Each sync run resolves selected conversations, runs status, imports, then exports. Manual, focus, activation, and file-change sync all use the same notification path, so background failures produce visible warnings. There is no single-flight guard, no cooldown, and no backoff.

## Desired Policy

Manual sync should be explicit and visible. Background sync should be quiet unless the user needs to act.

- Manual `Codex Usage: Sync Now`
  - Shows success.
  - Shows failure.
  - Bypasses cooldown and backoff, but still respects the single-flight guard.
- Auto sync on activation/focus
  - Runs at most once per focus cooldown window.
  - Uses a 5-minute default cooldown.
  - Logs transient failures to the output channel without a popup.
- Auto sync after session file changes
  - Runs after a calmer debounce window.
  - Uses a 30-second default debounce.
  - Coalesces multiple file changes into one sync.
- Sync off
  - Disposes file watchers.
  - Clears pending debounce timers.
  - Prevents new auto sync runs.
  - Suppresses stale auto failure notifications if a prior auto run finishes after sync has been disabled.
- Conflicts and configuration problems
  - Still produce visible warnings because user action is needed.
  - Warnings are rate-limited for auto sync.
- Repeated transient failures
  - Apply exponential-ish backoff for auto sync.
  - Start at 1 minute, then 5 minutes, capped at 15 minutes.

## Architecture

Add a small scheduler state inside `extensions/vscode/src/extension.ts`. Keep it private to the extension wrapper because it only coordinates VS Code triggers and notifications.

Proposed state:

- `syncDebounce`: existing file-change debounce timer.
- `syncInFlight`: whether a sync command sequence is currently running.
- `syncPendingReason`: optional queued follow-up reason when a trigger arrives during an active sync.
- `lastAutoSyncAt`: timestamp of the last auto sync start.
- `nextAutoSyncAllowedAt`: timestamp after failure backoff.
- `autoFailureCount`: consecutive auto failure count.
- `lastAutoWarningAt`: timestamp for rate-limiting visible auto warnings.

Add small pure helpers in `extensions/vscode/src/core.ts` for testability:

- `SYNC_FILE_CHANGE_DEBOUNCE_MS = 30_000`
- `SYNC_FOCUS_COOLDOWN_MS = 5 * 60_000`
- `SYNC_AUTO_WARNING_COOLDOWN_MS = 5 * 60_000`
- `syncBackoffMs(failureCount: number): number`
- `syncFailureRequiresNotification(message: string): boolean`

The extension should use these helpers but keep actual timers and VS Code calls in `extension.ts`.

## Sync Flow

Manual sync:

1. If sync is not configured, offer configuration.
2. If another sync is running, mark a manual follow-up as pending and show a short message such as "Codex sync is already running; another run will start afterward."
3. Run status/import/export.
4. Show success or failure notification.

Auto sync:

1. If sync is off or not configured, return without notification.
2. If current time is before `nextAutoSyncAllowedAt`, log that auto sync is skipped due to backoff.
3. For focus/activation, if current time is within the focus cooldown, skip quietly.
4. If another sync is running, set a pending auto reason and return.
5. Run status/import/export.
6. On success, reset failure count and backoff.
7. On conflict/configuration failure, show a rate-limited warning.
8. On transient failure, log only and advance backoff.

After any sync completes:

1. Clear `syncInFlight`.
2. If there is a pending reason and sync is still enabled, run one follow-up sync.
3. If sync was disabled while the prior run was active, discard the pending reason.

## Notification Rules

Manual:

- Success: `Codex sync complete.`
- Conflict/failure: visible warning/error with a readable message.

Auto:

- Success: output channel only.
- Conflict: visible warning, rate-limited.
- Missing sync folder or missing executable: visible warning, rate-limited.
- Access denied, lock, transient CLI failure, or generic nonzero exit: output channel only, with backoff.

The output channel should include the reason, action, and next retry timing when backoff applies.

## Settings

Do not add user-facing timing settings in this slice. Hard-coded constants are better for beta simplicity. If beta users need tuning later, we can expose advanced settings with clear descriptions.

Existing settings remain:

- `codexUsage.sync.enabled`
- `codexUsage.sync.autoPull`
- `codexUsage.sync.autoPush`

## Versioning And Packaging

This slice should bump the extension and Python package to `0.1.14`, update `CHANGELOG.md`, rebuild the bundled Windows executable, and rebuild the Windows VSIX.

## Testing

TypeScript tests should cover the pure scheduling helpers:

- Backoff is `1 min`, `5 min`, then capped at `15 min`.
- Conflict/configuration failures require notification.
- Generic transient failures do not require auto notification.

Extension build tests should still pass after scheduler changes.

Manual smoke should verify:

- Sync Off stops new auto sync after reload and immediately clears file-change timers.
- File changes coalesce into one sync after the debounce window.
- Focus does not trigger repeated syncs within the cooldown.
- Manual Sync Now still runs immediately.
- Auto sync failures are logged, not repeatedly shown as popups.

## Non-Goals

- Do not change the Python sync manifest format.
- Do not add cloud-provider integrations.
- Do not add user-facing timing settings.
- Do not change the project/conversation selection model.
- Do not change the CLI command names.
