from __future__ import annotations

from collections.abc import Iterable

from codex_usage.sync.inventory import normalize_selected_thread_ids
from codex_usage.sync.models import (
    LocalInventory,
    RemoteInventory,
    RemoteThreadEntry,
    SyncIssue,
)
from codex_usage.threads import ThreadInfo


def transfer_project_scope_issues(
    local: LocalInventory,
    remote: RemoteInventory,
    thread_ids: Iterable[str],
    expected_project_key: str,
) -> tuple[SyncIssue, ...]:
    expected = expected_project_key.strip()
    selected = normalize_selected_thread_ids(thread_ids)
    unresolved = next(
        (
            thread_id
            for thread_id in selected
            if thread_id not in local.threads
            and thread_id not in remote.index.threads
        ),
        None,
    )
    if unresolved is not None:
        return (
            SyncIssue(
                "unresolved_selected_task",
                "A selected task is not present in either transfer inventory.",
                unresolved,
            ),
        )
    project_keys = {
        project_key
        for thread_id in selected
        if (
            project_key := _selected_project_key(
                local.threads.get(thread_id),
                remote.index.threads.get(thread_id),
            )
        )
    }
    if len(project_keys) > 1:
        return (
            SyncIssue(
                "cross_project_selection",
                "Import and Export handle one project at a time. Choose tasks from one project.",
            ),
        )
    actual = next(iter(project_keys), "")
    if not expected or not actual or expected != actual:
        return (
            SyncIssue(
                "project_scope_mismatch",
                "The selected tasks do not match the project chosen for this transfer.",
            ),
        )
    return ()


def _selected_project_key(
    local_task: ThreadInfo | None,
    remote_task: RemoteThreadEntry | None,
) -> str:
    if local_task is None:
        return remote_task.project_key if remote_task is not None else ""
    if remote_task is None:
        return local_task.project_key
    local_identities = {local_task.project_key, *local_task.project_aliases}
    remote_identities = {remote_task.project_key, *remote_task.project_aliases}
    if local_identities.intersection(remote_identities):
        return remote_task.project_key
    return local_task.project_key
