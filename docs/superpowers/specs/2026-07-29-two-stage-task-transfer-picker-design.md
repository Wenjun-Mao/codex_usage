# Two-Stage Task Transfer Picker Design

Status: Approved

Date: 2026-07-29

## Goal

Make Import and Export visibly operate on one Codex project at a time without
representing the project itself as a selected task.

After choosing a project, users must see a dedicated task-selection screen that
starts empty, searches only that project's eligible tasks, and provides a clear
way to return to project selection.

## Root Cause Note

### What Failed

On Windows, choosing a project in the Export picker immediately selected more
than 100 rows. The selection count included the project row, the project appeared
to be another task, and there was no clear way to start from an empty task
selection or return to project choice.

### Why It Failed

The current picker models project activation and task selection in one
multi-select list:

- selecting a project programmatically selects every eligible child task;
- the active project row is inserted into the picker's selected-items collection;
- project and task search results share one list;
- switching projects is implemented as another selection change rather than
  navigation.

This is a domain-model mismatch. A project is the scope of one transfer, while
tasks are the selectable transfer contents. Treating both as peer selections
causes misleading counts and creates fragile event reconciliation in VS Code's
multi-select control.

### Correct Fix Layer

Separate project scope from task selection in the picker workflow and in its
state model. Do not patch the displayed count, add a special "clear all" row, or
hide the selected project while retaining the combined selection contract.

## Product Contract

Every Import and Export operation contains:

- exactly one project key;
- one or more selected task ids;
- only task ids that belong to the selected project.

The project is transfer context, not a selected item. It never contributes to
the selected count.

Review Transfer Status remains a cross-project, read-only task picker and does
not inherit this write-operation restriction.

## Interaction Flow

### Step 1: Choose A Project

Import and Export begin with a single-select project picker.

Suggested copy:

```text
Export Tasks: Choose a Project
Choose one project to export tasks from.
```

```text
Import Tasks: Choose a Project
Choose one project to import tasks into.
```

This screen contains project rows only. Each row may show its eligible task
count and identity details. Search filters project rows only.

Accepting one project advances to task selection. It does not select any tasks.

### Step 2: Select Tasks

The second screen is a multi-select picker containing only eligible tasks from
the chosen project.

Suggested copy:

```text
Export Tasks: Select Tasks from ops-board
Search tasks in ops-board.
```

```text
Import Tasks: Select Tasks for ops-board
Search tasks in ops-board.
```

No task is selected by default. The selected count therefore starts at zero and
counts tasks only.

Accept requires at least one selected task. An empty acceptance keeps the picker
open and displays a concise validation message.

### Back Navigation

The task screen exposes VS Code's native Back button. Back returns to the
project-only screen.

Going Back discards the current task selection. Choosing any project, including
the previous project, opens a fresh task screen with zero selected tasks.

Cancelling or hiding either screen cancels the entire transfer command without
changing files.

## State And Validation

Model navigation state separately from task selection:

```text
project step: selectedProjectKey is absent
task step: selectedProjectKey is present, selectedTaskIds may be empty
accepted: selectedProjectKey is present, selectedTaskIds is nonempty
```

Project rows must never enter the task selected-items collection. Task selection
events operate only on task rows already scoped to the chosen project, avoiding
the programmatic project/task selection reconciliation that caused the Windows
failure.

Before destination resolution, preflight, locks, or writes, defensive validation
must verify:

- exactly one project was selected;
- at least one task was selected;
- every selected task resolves to that project's eligible inventory.

The existing Python-core one-project boundary remains the final write guard.

## Operation Scope

- **Export:** use the two-stage flow and export tasks from exactly one project.
- **Import:** use the same two-stage structure for consistency and import tasks
  for exactly one project.
- **Review Transfer Status:** keep the existing cross-project read-only picker.

The transfer folder may continue to contain tasks from several projects
accumulated through separate operations.

## Testing

Pure selection tests must prove:

- activating a project selects zero tasks;
- selected item ids never include a project row;
- visible task rows belong only to the active project;
- switching or returning to a project starts with no selected tasks;
- cross-project task ids are rejected.

VS Code adapter tests must prove:

- project and task steps use distinct item lists and copy;
- task selection starts empty;
- the displayed selected count reflects tasks only;
- Back returns to project selection and clears task state;
- task search cannot expose projects or tasks from another project;
- delayed programmatic selection events on Windows cannot undo a user task
  selection;
- accepting zero tasks does not complete the command.

Existing transfer integration and core validation tests continue to guard the
one-project write boundary.

## Documentation

Update user-facing transfer instructions to describe:

1. choosing one project;
2. choosing one or more tasks from that project;
3. using Back to choose a different project;
4. repeating the operation to transfer tasks from another project.

Update changelog copy to call out the empty-by-default task picker and corrected
selection count.

## Non-Goals

- Optimizing the time required to build the task inventory.
- Adding multi-project Import or Export.
- Adding persistent task selections between picker invocations.
- Changing the cross-project Review Transfer Status workflow.

## Supersession

This design replaces the combined-picker and all-tasks-selected portions of:

- ADR 0017, One Project Per Transfer Operation;
- the "One-Project Selection UX" section of the Post-Import Codex Task
  Registration Design.

The one-project transfer boundary and all other registration behavior remain
unchanged.
