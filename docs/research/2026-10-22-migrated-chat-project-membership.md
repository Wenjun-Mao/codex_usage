# Migrated Chat Project Membership

Date: 2026-10-22. Investigation and bounded local recovery, not a plugin release.

## Observed Failure

Two previously imported, recently used local chats appeared in the desktop
sidebar as older Windows-host copies. The remote cache retained the same chat IDs,
old Windows working directories and old names/activity times. The local Codex
catalog and native `read_thread` responses retained the recent local names,
Mac working directories and conversation history.

Observed runtime: desktop `26.1016.51333`, bundled
`codex-cli 0.163.0-alpha.11`.

Both local chats had compatible legacy `thread-project-assignments` entries but
null app-server `projectId` values. Their destination projects already existed
in the app-server project catalog. Desktop state also contained an explicit
legacy-to-server project ID mapping. The installed desktop implementation now
synchronizes project membership through `thread/metadata/update`; its migration
checkpoints are separate from the legacy registry.

This establishes a registration compatibility gap, not missing recent logs.
The exact update that introduced the visible regression was not established.
The built-in project-move tool selected the local server record but rejected
both operations because the sidebar summary still belonged to the old host.
No successful native-tool move is claimed.

## Bounded Recovery

Used the installed Codex app-server JSON-RPC interface over a short-lived local
stdio connection. Its generated schema explicitly supports assigning an
existing project with `thread/metadata/update.projectId`.

- Selected only the two verified recent local chats.
- Read both first and required exact IDs, local working directories and no
  conflicting current server project assignment.
- Assigned each existing, explicitly mapped server project ID.
- Verified returned identity, working directory and project ID, then checked
  persisted membership with read-only SQL and reread through the native tool.
- Existing names and update/activity timestamps remained unchanged.
- Started no turns; performed no direct SQLite or global-state writes, remote
  cache removal, remote-host operations, reimport, CI, publication or install.

The owned app-server process exited. Temporary generated schemas were removed.
The two other old remote chat IDs shown in the screenshot were not present in
the local catalog or local active/archived rollout filenames; they were not
silently imported or rebound.

Persisted registration repair was verified independently. Computer-use access
to Codex was denied, so the agent did not verify the sidebar visually. The owner
subsequently confirmed on 2026-10-22 that the projects look fixed and supplied a
screenshot showing the restored local chat labels. This closes human sidebar
acceptance for the bounded repair, not general importer compatibility.

## Importer Follow-Up

ADR 0029's tested legacy JSON binding is not sufficient evidence of current
app-server project membership. No importer code changed in this investigation.
Before expanding compatibility, define capability detection, verified project
mapping and partial-success behavior for server-owned membership. Do not clear
migration checkpoints, infer project IDs from names, edit SQLite directly or
erase remote copies to hide collisions.

Regression cases should cover an imported local chat sharing an ID with a stale
remote summary, unchanged reimports, correct existing membership, conflicting
membership, unsupported runtimes and interrupted registration. Visible sidebar
acceptance must remain distinct from server registration success.
