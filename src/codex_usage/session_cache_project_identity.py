from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from codex_usage.project_identity import resolve_project_identity
from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_inventory import SessionFileInventoryEntry


def refresh_cached_project_identities(
    connection: sqlite3.Connection,
    inventory: Iterable[SessionFileInventoryEntry],
) -> frozenset[str]:
    """Reattribute unchanged cached rows after a verified local remote change."""
    affected_task_ids: set[str] = set()
    connection.execute("begin immediate")
    try:
        for entry in inventory:
            checkpoint = load_parser_checkpoint(connection, entry.file_key, entry.path)
            if checkpoint is None:
                continue
            metadata = checkpoint.state.root_metadata or checkpoint.state.metadata
            identity = resolve_project_identity(metadata)
            if not identity.uses_current_checkout_origin:
                continue
            aliases_json = json.dumps(list(identity.aliases))
            changed_rows = list(
                connection.execute(
                    """
                    select distinct session_id from usage_records
                    where file_key = ?
                      and (
                          project_key != ? or project_label != ?
                          or project_aliases_json != ? or git_repository_url != ?
                      )
                    """,
                    (
                        entry.file_key,
                        identity.key,
                        identity.label,
                        aliases_json,
                        identity.git_repository_url,
                    ),
                )
            )
            metadata_changed = connection.execute(
                """
                update session_metadata
                set project_key = ?, project_label = ?, project_aliases_json = ?,
                    git_repository_url = ?
                where file_key = ?
                  and (
                      project_key != ? or project_label != ?
                      or project_aliases_json != ? or git_repository_url != ?
                  )
                """,
                (
                    identity.key,
                    identity.label,
                    aliases_json,
                    identity.git_repository_url,
                    entry.file_key,
                    identity.key,
                    identity.label,
                    aliases_json,
                    identity.git_repository_url,
                ),
            ).rowcount
            if not changed_rows and not metadata_changed:
                continue
            connection.execute(
                """
                update usage_records
                set project_key = ?, project_label = ?, project_aliases_json = ?,
                    git_repository_url = ?
                where file_key = ?
                """,
                (
                    identity.key,
                    identity.label,
                    aliases_json,
                    identity.git_repository_url,
                    entry.file_key,
                ),
            )
            affected_task_ids.update(str(row["session_id"]) for row in changed_rows)
            if metadata_changed and checkpoint.session_id:
                affected_task_ids.add(checkpoint.session_id)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return frozenset(affected_task_ids)
