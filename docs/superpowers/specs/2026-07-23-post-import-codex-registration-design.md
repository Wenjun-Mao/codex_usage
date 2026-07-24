# Post-Import Codex Task Registration Design

Status: Approved

Date: 2026-07-23

## Goal

Make every successful Task Transfer Import deterministically discoverable by Codex
without writing Codex's private SQLite database or relying on an incidental
filesystem scan.

Imported task JSONLs must remain portable across Windows x64 and macOS Apple
Silicon. After Import, Codex must own the state-database update through its
supported `app-server` protocol.

Constrain each Import and Export operation to exactly one Codex project so one
operation maps to one source or destination checkout. Keep the transfer folder
multi-project across separate operations.

## Root Cause Note

### What Failed

Two tasks imported into the local `Letta-Open-ADE` project had valid local JSONL
files, rewritten macOS cwd values, matching Git identity, and entries in
`session_index.jsonl`. They did not appear in the Codex desktop sidebar after
restarting Codex.

### Why It Failed

Current Import stops after updating filesystem artifacts and
`session_index.jsonl`. Modern Codex task listing is state-database-first. Its
one-time rollout backfill had already completed, so a later app restart did not
rescan newly copied rollout files.

Earlier imports appeared because a live Codex client happened to take a
filesystem-backed read/list path. That path performed Codex's internal read
repair and inserted the task into the state database. This incidental behavior
was never part of Task Transfer's contract.

### Evidence

Before the registration spike:

- task ids `019db09f-a9e0-7d93-a8b8-7697d67ad5bc` and
  `019db5c7-5771-7512-9dc7-dc2ba033f712` had valid rollout files;
- both ids were present in `session_index.jsonl`;
- neither id existed in `state_5.sqlite`'s `threads` table;
- Codex's recorded rollout backfill status was already `complete`.

A no-code spike started the Codex binary bundled with the macOS desktop app,
initialized `codex app-server`, and sent `thread/read` with
`includeTurns: false` for each id. Codex logged:

```text
state db discrepancy during find_thread_path_by_id_str_in_subdir: falling_back
state db discrepancy during read_repair_rollout_path: upsert_needed (slow path)
```

Both calls returned the expected tasks. Both ids then existed in the state
database and appeared immediately in Codex's normal task-list API. The already
running desktop sidebar remained cached and displayed them only after Codex was
restarted.

### Correct Fix Layer

Add a post-import adapter that invokes Codex's supported `app-server` API.
Codex itself reads each imported rollout and performs its own state repair.

Do not:

- insert, update, or migrate Codex SQLite rows directly;
- reset Codex's completed backfill marker;
- force a filesystem-wide `thread/list` scan;
- depend on whether the desktop app happened to be running during Import.

## Product Contract

Import remains an explicit, manual file-transfer operation. Its existing
all-or-nothing preflight and atomic copy guarantees remain unchanged.

Each Import or Export selects tasks from exactly one Codex project:

- all tasks in that project start selected;
- the user may deselect individual tasks;
- tasks from another project cannot join the same operation;
- the transfer folder may retain tasks from many projects accumulated across
  separate operations;
- Export updates only the chosen project and does not remove other projects;
- Review Transfer Status remains cross-project because it is read-only.

Use **project** in user-facing copy rather than **repository**. Git identity still
validates Git-backed projects, while non-Git Codex projects remain supported.

After the transfer engine returns:

1. Determine which selected task ids now have a certified local copy.
2. Start one Codex `app-server` process.
3. Register those ids through targeted `thread/read` calls.
4. Report transfer and registration as one user-visible outcome.

Registration runs for:

- every selected task after a fully completed Import, including tasks for which
  no file change was needed;
- only ids in `result.pulled` after a partial Import whose completed copies are
  certified.

Registration does not run for:

- Export;
- Review Transfer Status;
- a blocked or conflicted Import with no certified local copy;
- an Import whose file completion is unknown.

Registering unchanged selected tasks is intentional. Re-running Import must heal
tasks copied by an older plugin version without carrying a one-time migration.

## One-Project Selection UX

The one-project boundary must be visible before, during, and after each transfer.
It must not exist only as validation after the user confirms.

Import begins with one combined project/task picker:

```text
Import Tasks: Choose One Project
One project per import. All tasks start selected.
```

Export uses:

```text
Export Tasks: Choose One Project
One project per export. All tasks start selected.
```

Choosing a project keeps that picker open, makes the chosen project visibly
active, and presents only its task choices as selectable. All of its eligible
tasks start selected. The user can adjust the task subset or switch projects
before confirming.

Switching projects clears the previous project's task selection and selects all
eligible tasks in the newly active project. Never silently combine, discard, or
move task selections across projects.

Defensive validation rejects a cross-project task set before project resolution
or file preflight, even if a custom or future UI bypasses the picker constraint.
The error states that Import or Export handles one project at a time.

Project-specific operation copy includes the project label:

```text
Importing 2 tasks into Letta-Open-ADE
Choose destination folder for Letta-Open-ADE
Imported 2 tasks into Letta-Open-ADE.

Exporting 2 tasks from Letta-Open-ADE
Exported 2 tasks from Letta-Open-ADE to the transfer folder.
```

When Git identity is available, the picker detail may show the normalized
repository identity for disambiguation. The primary label remains the Codex
project label.

Review Transfer Status clearly says that it reviews tasks across projects and
does not inherit the one-project write restriction.

## Completion And Failure Semantics

Filesystem transfer and Codex registration are distinct observable boundaries.
Registration failure must not roll back a certified imported file. A later
Import can retry registration without copying the file again.

Outcomes:

- **Transfer and registration succeed:** report Import success.
- **Files are already current and registration succeeds:** report that no file
  changes were needed and that the selected tasks were registered.
- **Certified files exist but registration fails:** report partial completion.
  State that the files are safe, identify the failed task count, and tell the
  user to retry Import after resolving Codex availability.
- **Only some certified task ids register:** report the successful and failed
  counts. Do not describe the whole Import as successful.
- **Transfer is blocked before copying:** preserve the existing blocked/conflict
  result and skip registration.

Task-specific registration failures are logged with the task id. Notifications
do not expose rollout contents or private Codex paths.

## Client Refresh Contract

Registration updates durable Codex state immediately. A Codex client that is
already running may retain a cached task list.

After at least one task is registered, completion copy says:

```text
Open or restart Codex to display the imported tasks.
```

The full success message includes the project label:

```text
Imported 2 tasks into Letta-Open-ADE. Open or restart Codex to display them.
```

For the official Codex VS Code extension, reloading VS Code remains an equivalent
client refresh. The plugin does not attempt to terminate, restart, or automate
another Codex client.

## Codex Executable Discovery

Discovery returns ordered candidates. The app-server client tries candidates in
order and continues after a candidate cannot be started or initialized.

### Common Priority

1. A nonempty official `chatgpt.cliExecutable` override.
2. The binary bundled with the official `openai.chatgpt` VS Code extension.
3. The current platform's Codex desktop app runtime.
4. `codex` or `codex.exe` on `PATH`.

Each candidate is deduplicated by normalized native path. A candidate is usable
only when it successfully starts and completes the app-server initialization
handshake. Child processes use direct argument arrays with `shell: false`.

### Official VS Code Extension

Resolve the installed extension through the VS Code extension API and mirror its
platform mapping:

- Windows x64: `bin/windows-x86_64/codex.exe`
- macOS Apple Silicon: `bin/macos-aarch64/codex`

Do not activate the official extension merely to obtain `extensionPath`.

### macOS Desktop Fallback

Check known app resource locations only on macOS, including the installed
application resource path:

```text
/Applications/ChatGPT.app/Contents/Resources/codex
```

User-local application locations may be checked using the same bundle-relative
resource path. macOS app paths are never evaluated on Windows.

### Windows Desktop Fallback

Prefer the desktop app's executable copy relocated to a user-writable location:

```text
%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe
%LOCALAPPDATA%\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\OpenAI\Codex\bin\codex.exe
```

Also inspect immediate version/hash children under the per-user Codex `bin`
directory for `codex.exe`.

As a final desktop candidate, query the installed `OpenAI.Codex` AppX package
location and check:

```text
<InstallLocation>\app\resources\codex.exe
```

The `WindowsApps` package is a last resort because normal processes may be denied
execution access. A protected or inaccessible package candidate is skipped
without blocking later candidates.

The current package matrix remains Windows x64 and macOS Apple Silicon. Windows
ARM64 and Intel macOS are outside this release.

## App-Server Protocol

Use one short-lived child process for one Import registration batch:

```text
codex app-server --stdio
```

The client sends newline-delimited JSON-RPC:

1. `initialize` with client name `codex-usage` and the extension version.
2. `initialized`.
3. One `thread/read` request per unique task id with `includeTurns: false`.

The client:

- accepts chunked stdout and out-of-order request responses;
- keeps stderr separate from JSON-RPC stdout;
- correlates every response by request id;
- treats a matching `thread.id` as successful registration;
- treats JSON-RPC errors, mismatched ids, early process exit, malformed protocol,
  or timeout as registration failure;
- applies bounded startup/request timeouts and terminates the child after the
  batch settles;
- retries only transient process startup/initialization failure before advancing
  to the next executable candidate.

No prompt is sent, no turn is started, and no model request is made.

## Architecture And Ownership

### Python Transfer Engine

The Python engine remains authoritative for:

- inventory, project resolution, and preflight;
- cwd rewriting and project identity validation;
- atomic task-file and index updates;
- transfer completion certification;
- portable format and local baseline bookkeeping.

The Python result schema remains the source of `selected`, `pulled`, planner rows,
and completion state. It does not discover Codex clients or implement app-server
JSON-RPC.

### VS Code Extension

The extension remains the operation orchestrator and gains two focused modules:

- executable candidate discovery;
- Codex app-server registration.

`TaskTransferController` receives registration through its port. It selects the
ids allowed by the completion rules, awaits registration before formatting the
final notification, and logs structured registration diagnostics.

The combined picker returns one selected project identity plus its selected task
ids. The controller validates that every selected task belongs to that project
before destination resolution or execution. The Python invocation receives the
same project key as an explicit operation constraint so the core enforces the
contract independently of the UI.

Keep discovery and protocol parsing independent of the VS Code API where
possible. The VS Code adapter supplies extension paths, platform data,
environment variables, and notifications.

## Security And Resilience

- Never pass rollout content through command-line arguments.
- Validate task ids as the exact selected ids before issuing requests.
- Spawn every executable directly with fixed app-server arguments.
- Bound stdout/stderr retained for errors.
- Use per-request and whole-batch timeouts.
- Terminate a stalled child and continue to the next executable candidate only
  when no task request has produced an ambiguous result.
- Do not retry a task after an explicit `thread/read` not-found/protocol error.
- Do not inspect or mutate Codex SQLite to verify registration.
- Do not broaden filesystem permissions to reach a protected Windows app bundle.

## Testing And Guardrails

Use test-driven implementation.

### Executable Discovery Tests

- official CLI override wins when valid;
- official extension paths map correctly for Windows x64 and macOS arm64;
- desktop paths are evaluated only on their matching platform;
- Windows per-user, Store LocalCache, version/hash, and AppX candidates are
  ordered and deduplicated;
- inaccessible `WindowsApps` candidates are skipped;
- PATH remains the final cross-platform candidate;
- unsupported platform/architecture combinations fail clearly.

### App-Server Client Tests

Use a fake child process to cover:

- initialize, initialized, and targeted `thread/read` requests;
- chunked JSON lines and out-of-order responses;
- multiple successful task registrations through one process;
- JSON-RPC task errors and mismatched thread ids;
- malformed stdout, stderr warnings, early exit, timeout, and cleanup;
- fallback from an unusable executable candidate;
- no model turn or prompt method.

### Task Transfer Tests

- Import and Export accept one selected project with any nonempty task subset;
- all eligible tasks in the chosen project start selected;
- switching projects clears the previous selection and selects the new project's
  eligible tasks;
- cross-project task ids are rejected in both the controller and Python core
  before destination resolution or writes;
- the transfer folder preserves projects from earlier operations;
- Review Transfer Status remains cross-project;
- picker, destination, progress, success, blocked, and partial-failure copy names
  the selected project and states the one-project rule where relevant;
- completed Import registers every selected id, including unchanged tasks;
- partial certified Import registers only `result.pulled`;
- conflict, blocked, Export, and Review operations do not register;
- registration success adds open/restart guidance;
- complete and partial registration failures never claim full success;
- registration failure does not undo imported files;
- rerunning an unchanged Import retries registration.

### Integration And Manual Verification

- package a fake app-server fixture for Windows x64 and macOS arm64 smoke tests;
- run the full Python and extension suites, TypeScript build, lint, and packaging
  checks;
- manually import a previously unseen task with Codex closed, register it, open
  Codex, and confirm it appears under the rewritten project;
- manually repeat with Codex open and confirm that restarting Codex refreshes the
  cached sidebar;
- validate the Windows discovery order on a Windows x64 machine before release.

The completed macOS feasibility spike is retained as design evidence, not as a
substitute for automated tests.

## Documentation And Release

Update both READMEs and changelogs to state:

- each Import or Export handles one Codex project and any selected tasks within
  it;
- the transfer folder may contain multiple projects accumulated across separate
  operations;
- Import registers tasks with Codex after copying them;
- users should open or restart Codex, or reload VS Code, to refresh the task list;
- registration uses an installed official Codex runtime and does not invoke a
  model;
- imported files remain safe when registration fails and Import can be retried.

Add a troubleshooting entry for "files imported but tasks are not visible" with
executable discovery and retry guidance.

## Durable Decision Record

Add ADR 0016 to record that Task Transfer may invoke Codex's supported
`app-server` to register imported rollouts. This supersedes only ADR 0014's
prohibition on all Codex state updates.

The durable guardrail remains: Codex Usage never writes private Codex databases
or project registries directly.

Add ADR 0017 to record the one-project-per-Import-or-Export contract. The
transfer folder remains multi-project and Review Transfer Status remains
cross-project.

## Non-Goals

- Refresh or restart the Codex desktop UI programmatically.
- Add automatic/background Task Transfer.
- Perform filesystem-wide Codex reconciliation.
- Patch Codex SQLite or reset backfill state.
- Start a task turn or make a model request.
- Add Windows ARM64, Intel macOS, or Linux packaging in this release.
