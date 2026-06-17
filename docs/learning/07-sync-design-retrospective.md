# Sync Design Retrospective

Sync became complex because the user problem was real: switching computers should not require remembering to write a handoff.

## Original Pain

The uncomfortable workflow was:

1. Work on a Codex conversation on one machine.
2. Move to another machine.
3. Manually recreate context or start a new thread.
4. Risk forgetting important state.

A handoff command would still require the user to remember to run it. That would not solve the underlying habit problem.

## Rejected Big Hammer

The tempting idea was to sync the whole `.codex` directory.

That was rejected because `.codex` may contain:

- auth;
- config;
- caches;
- logs;
- SQLite databases;
- environment-specific paths;
- files Codex may be actively writing.

Whole-directory sync is easy to explain and hard to make safe.

## Chosen MVP

The selected-conversation sync MVP copies only:

- selected session JSONL files;
- matching session index entries;
- sync manifests and metadata.

It uses a bring-your-own local sync folder, such as OneDrive, Dropbox, Syncthing, or a network drive. The extension does not call cloud APIs.

## Project-First UX

The first thread picker was confusing because users think in projects first, then conversations.

The better setup flow is:

1. choose sync folder;
2. choose projects with estimated sync sizes;
3. choose all conversations in those projects or selected conversations.

This matches the dashboard mental model.

## Why Three-Way State Was Needed

Two-way hash comparison produced false conflicts. If local and remote differed, the engine could not tell whether:

- one machine simply appended new events;
- both machines changed differently;
- local and remote were already known safe descendants.

The fix was to add base/local/remote thinking:

- base: last content this machine successfully synced;
- local: current local JSONL;
- remote: sync-folder JSONL.

For Codex JSONL, append-only prefix comparison is a safe automatic rule. If one side is a prefix of the other, the longer file can fast-forward. If both sides have different tails, stop and report a conflict.

## Scheduler Lesson

Automatic sync should be quiet and calm:

- use status bar for normal state;
- debounce file changes;
- apply focus cooldown;
- apply failure backoff;
- show notifications only for manual sync or action-needed failures.

Future me: background automation should earn trust by being boring. Repeated popups are a product bug, even if the underlying operation is technically correct.

## Remaining Sync Boundaries

The MVP still intentionally does not sync SQLite memory rows. It reports diagnostics when memory rows exist.

This is a good boundary until there is evidence that a smaller safe state file must be included.

