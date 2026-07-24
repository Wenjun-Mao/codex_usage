# ADR 0017: One Project Per Transfer Operation

Status: Accepted

Date: 2026-07-23

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
nonempty subset of its eligible tasks. Start with every eligible task in the
chosen project selected and allow individual deselection.

Keep project choice and task choice in one visible picker flow. State the
one-project rule in the picker title or helper text, name the project in
destination, progress, and result copy, and reject cross-project selections
before any write.

Keep the transfer folder multi-project across separate operations. Export changes
only the chosen project. Keep Review Transfer Status cross-project because it is
read-only.

## Alternatives Considered

- Keep multi-project Import and prompt for one destination directory per project.
- Restrict only Import while allowing multi-project Export.
- Restrict each transfer folder permanently to one project.
- Silently use the first selected project and discard tasks from other projects.
- Replace the combined picker with unrelated project and task dialogs.

## Consequences

Every write operation has one clear project identity and at most one unresolved
destination directory. Moving several projects requires several explicit
operations, while the same transfer folder can continue accumulating their
tasks.

The picker needs active-project state and must reset task selection visibly when
the user switches projects. Both the extension and Python core enforce the
one-project boundary.

## Guardrails

- Use **project** in user-facing copy; preserve support for non-Git projects.
- Start all eligible tasks in the active project selected.
- Never silently combine or discard selections from different projects.
- Reject cross-project selections before destination resolution, preflight, or
  file writes.
- Name the selected project in folder prompts, progress, and results.
- Preserve unrelated projects already present in the transfer folder.
- Do not apply the write restriction to cross-project status review.

## Supersession

This decision narrows ADR 0014's fresh per-operation selection contract to one
project per Import or Export. ADR 0014's manual triggers, all-or-nothing
preflight, transient destination bindings, and portable multi-project transfer
format remain unchanged.
