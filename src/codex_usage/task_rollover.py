from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codex_usage.session_cache import resolve_cache_dir
from codex_usage.storage_context import load_storage_context
from codex_usage.task_backup import create_task_backup, select_backup_tree
from codex_usage.task_backup.models import BackupResult, CompressionPreset
from codex_usage.task_backup.progress import ProgressCallback, ignore_progress


class RolloverPreparationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RolloverResult:
    backup: BackupResult
    task_title: str
    project_label: str
    starter_prompt: str
    checklist: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "backup": self.backup.to_dict(),
            "task_title": self.task_title,
            "project_label": self.project_label,
            "starter_prompt": self.starter_prompt,
            "checklist": list(self.checklist),
        }


def prepare_task_rollover(
    tree_id: str,
    output_path: Path,
    *,
    session_dirs: list[Path],
    cache_dir: Path | None = None,
    compression: CompressionPreset = "maximum",
    progress: ProgressCallback = ignore_progress,
) -> RolloverResult:
    context = load_storage_context(session_dirs=session_dirs, cache_dir=cache_dir)
    tree = next(
        (
            candidate
            for candidate in context.insights.task_trees
            if candidate.root_task_id == tree_id
        ),
        None,
    )
    if tree is None:
        raise RolloverPreparationError(f"Task tree not found: {tree_id}")
    if not tree.analysis_complete:
        raise RolloverPreparationError(
            "Complete History Amplification analysis before preparing rollover"
        )
    if not tree.can_prepare_rollover:
        raise RolloverPreparationError(
            "Rollover is available only for an analyzed large or history-amplified task tree"
        )
    if output_path.exists():
        raise RolloverPreparationError(
            "Rollover requires a new backup path; existing archives are never replaced"
        )

    selection = select_backup_tree(context, tree_id)
    if not selection.recovery_ready:
        details = ", ".join(selection.diagnostics) or "ownership is unresolved"
        raise RolloverPreparationError(
            f"Rollover requires a recovery-ready task tree: {details}"
        )
    backup = create_task_backup(
        selection,
        output_path,
        refresh_selection=lambda: select_backup_tree(
            load_storage_context(session_dirs=session_dirs, cache_dir=cache_dir),
            tree_id,
        ),
        compression=compression,
        replace_existing=False,
        progress=progress,
        lock_path=resolve_cache_dir(session_dirs, cache_dir) / "task-backup.lock",
    )
    if not backup.recovery_ready:
        raise RolloverPreparationError(
            "The verified archive is salvage-only, so rollover preparation was stopped"
        )
    return RolloverResult(
        backup=backup,
        task_title=tree.title,
        project_label=tree.project_label,
        starter_prompt=_starter_prompt(
            tree.title,
            tree.project_label,
            backup,
        ),
        checklist=_rollover_checklist(),
    )


def _starter_prompt(
    task_title: str,
    project_label: str,
    backup: BackupResult,
) -> str:
    return f"""Continue the work from the prior Codex task in a fresh root task.

Project: {project_label or '[same Codex project]'}
Prior task: {task_title or '[prior task]'}

Goal:
[State the outcome this task should achieve.]

Current state:
[Summarize what is already implemented or decided.]

Verification completed:
[List tests, checks, or evidence already completed.]

Remaining work:
[List the next concrete steps and unresolved decisions.]

Key paths:
[List the repository paths and files the new task should inspect first.]

Recovery reference:
Verified backup: {backup.archive_path.name}
SHA-256: {backup.archive_sha256}
Compression: {backup.compression}
Use the backup only for recovery; do not treat it as live project state.
"""


def _rollover_checklist() -> tuple[str, ...]:
    return (
        "Create a fresh root task in the same Codex project.",
        "Paste the starter prompt and replace every bracketed placeholder.",
        "Verify the new task opens the expected repository and can continue the work.",
        "Keep the verified backup until the replacement task is confirmed usable.",
        "Only after verification, delete the old task from inside Codex if desired.",
    )
