# ADR 0017: One Project Per Transfer Operation

Status: Accepted

Date: 2026-07-23

Amended: 2026-07-29

## Context

Task Transfer allowed one Import or Export selection to span several Codex
projects. Import then needed separate destination resolution for each project,
even though each folder picker selects only one directory at a time. This made a
single operation look as though it had one destination while internally
performing several unrelated project transfers.

The primary usage scenario is moving selected Codex tasks for one project between
computers and operating systems.

## Decision

Constrain every Import and Export operation to exactly one Codex project and any
nonempty subset of its eligible tasks.

Use a two-stage picker flow. First choose one project from a project-only,
single-select screen. Then choose tasks from a task-only, multi-select screen.
Start the task screen with no tasks selected. The project is transfer context,
not a selected item, and never contributes to the task-selection count.

Provide native Back navigation from task selection to project selection. Going
Back discards the current task selection, and entering any project starts with
no tasks selected. State the one-project rule in picker copy, name the project
in destination, progress, and result copy, and reject cross-project selections
before any write.

Keep the transfer folder multi-project across separate operations. Export changes
only the chosen project. Keep Review Transfer Status cross-project because it is
read-only.

## Alternatives Considered

- Keep multi-project Import and prompt for one destination directory per project.
- Restrict only Import while allowing multi-project Export.
- Restrict each transfer folder permanently to one project.
- Silently use the first selected project and discard tasks from other projects.
- Retain the combined project/task multi-select picker and add a clear-all
  action.
- Preselect every task after project choice and rely on users to deselect the
  tasks they do not want.
- Keep the project in the selected-items collection but exclude it only from the
  displayed count.

## Consequences

Every write operation has one clear project identity and at most one unresolved
destination directory. Moving several projects requires several explicit
operations, while the same transfer folder can continue accumulating their
tasks.

The picker needs explicit navigation state and task-selection state. Moving
between project and task screens resets task selection visibly. Both the
extension and Python core enforce the one-project boundary.

## Guardrails

- Use **project** in user-facing copy; preserve support for non-Git projects.
- Show projects and tasks on separate picker screens.
- Never count or represent the project as a selected task.
- Start every task-selection screen with zero selected tasks.
- Search only within the rows shown by the current screen.
- Back navigation clears task selection before returning to project choice.
- Never silently combine or discard selections from different projects.
- Require every selected task id to resolve from the local or transfer
  inventory before accepting the declared project.
- Reject cross-project selections before destination resolution, preflight, or
  file writes. Use read-only local and transfer inventory probes before lock
  creation, transfer-format migration, session-directory creation, or cache
  writes.
- Name the selected project in folder prompts, progress, and results.
- Preserve unrelated projects already present in the transfer folder.
- Do not apply the write restriction to cross-project status review, and never
  migrate or lock the transfer folder while reviewing it.

## Supersession

This decision narrows ADR 0014's fresh per-operation selection contract to one
project per Import or Export. ADR 0014's manual triggers, all-or-nothing
preflight, transient destination bindings, and portable multi-project transfer
format remain unchanged.
