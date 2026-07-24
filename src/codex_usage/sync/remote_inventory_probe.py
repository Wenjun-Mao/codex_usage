from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from codex_usage.sync.constants import (
    LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
    LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    REMOTE_TRANSFER_FORMAT_VERSION,
    SYNC_INDEX_FILENAME,
    TRANSFER_TASKS_DIRNAME,
)
from codex_usage.sync.errors import (
    MalformedSyncIndexError,
    TransferFormatMigrationError,
)
from codex_usage.sync.format_migration_layout import (
    guard_index,
    guard_legacy_file,
    guard_task_file,
    jsonl_files,
    legacy_layout_error,
    scan_layout,
    validate_file_claims,
)
from codex_usage.sync.io import read_bytes_with_snapshot
from codex_usage.sync.models import RemoteIndex, RemoteInventory, SyncFileSnapshot
from codex_usage.sync.remote_reconciliation import (
    materialize_selected_remote,
    reconcile_remote_discovery,
)


def probe_remote_inventory(root: Path) -> RemoteInventory:
    """Read either supported transfer layout without locking or migrating it."""
    layout = scan_layout(root)
    index_value, index_snapshot = read_remote_index_value(root)
    if index_value is None:
        if layout.legacy_exists:
            raise TransferFormatMigrationError(
                f"Cannot read {LEGACY_TRANSFER_CONVERSATIONS_DIRNAME}/ without "
                f"{SYNC_INDEX_FILENAME}"
            )
        persisted = RemoteIndex(REMOTE_TRANSFER_FORMAT_VERSION, "", {})
        return _reconcile(
            root,
            persisted,
            index_snapshot,
            _v3_jsonl_files(layout.task_files),
            TRANSFER_TASKS_DIRNAME,
        )

    format_version = remote_format_version(index_value)
    if format_version == 1:
        raise legacy_layout_error()
    if format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        persisted = parse_remote_index(
            index_value,
            LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
        )
        validate_file_claims(persisted, LEGACY_TRANSFER_CONVERSATIONS_DIRNAME)
        return _reconcile(
            root,
            persisted,
            index_snapshot,
            jsonl_files(
                layout.legacy_files,
                LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
            ),
            LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
        )
    if format_version == REMOTE_TRANSFER_FORMAT_VERSION:
        persisted = parse_remote_index(index_value, REMOTE_TRANSFER_FORMAT_VERSION)
        validate_file_claims(persisted, TRANSFER_TASKS_DIRNAME)
        return _reconcile(
            root,
            persisted,
            index_snapshot,
            _v3_jsonl_files(layout.task_files),
            TRANSFER_TASKS_DIRNAME,
        )
    raise MalformedSyncIndexError(
        f"Unsupported remote transfer format version {format_version}"
    )


def materialize_probed_remote(
    root: Path,
    inventory: RemoteInventory,
    selected_thread_ids: Iterable[str],
) -> RemoteInventory:
    """Materialize a probe while preserving the read-only layout contract."""
    if inventory.index.format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        materialized = materialize_selected_remote(
            root,
            inventory,
            inventory.index.threads,
            lambda path: guard_legacy_file(root, path),
            propagate_io_errors=True,
        )
        validate_v2_inventory(materialized)
        return materialized
    return materialize_selected_remote(
        root,
        inventory,
        selected_thread_ids,
        lambda path: guard_task_file(root, path),
    )


def validate_v2_inventory(inventory: RemoteInventory) -> None:
    if inventory.issues:
        details = "; ".join(issue.message for issue in inventory.issues)
        raise TransferFormatMigrationError(
            f"Version-2 migration validation failed: {details}"
        )

    validate_file_claims(
        inventory.index,
        LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    )
    for thread_id, entry in inventory.index.threads.items():
        snapshot = inventory.files.get(thread_id)
        if snapshot is None or not snapshot.exists:
            raise TransferFormatMigrationError(f"Remote task {entry.file} is missing")
        persisted_entry = inventory.persisted_index.threads.get(thread_id)
        if persisted_entry is None or persisted_entry.file != entry.file:
            continue
        mismatches: list[str] = []
        if persisted_entry.sha256 != snapshot.sha256:
            mismatches.append("sha256")
        if persisted_entry.size_bytes != snapshot.size_bytes:
            mismatches.append("size_bytes")
        if mismatches:
            fields = " and ".join(mismatches)
            raise TransferFormatMigrationError(
                f"Remote task {entry.file} does not match indexed {fields}"
            )


def read_remote_index_value(
    root: Path,
) -> tuple[dict[str, Any] | None, SyncFileSnapshot]:
    path = root / SYNC_INDEX_FILENAME
    guard_index(root)
    contents, snapshot = read_bytes_with_snapshot(path)
    if contents is None:
        return None, snapshot
    try:
        value = json.loads(contents)
        if not isinstance(value, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        return value, snapshot
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
        raise MalformedSyncIndexError(
            f"Malformed {SYNC_INDEX_FILENAME}: {error}"
        ) from error


def remote_format_version(value: dict[str, Any]) -> int:
    version = value.get("format_version")
    if type(version) is not int:
        raise MalformedSyncIndexError(
            f"Malformed {SYNC_INDEX_FILENAME}: format_version must be an integer"
        )
    return version


def parse_remote_index(value: dict[str, Any], expected_version: int) -> RemoteIndex:
    try:
        return RemoteIndex.from_dict(value, expected_format_version=expected_version)
    except (ValueError, TypeError) as error:
        raise MalformedSyncIndexError(f"Malformed {SYNC_INDEX_FILENAME}: {error}") from error


def _reconcile(
    root: Path,
    persisted: RemoteIndex,
    index_snapshot: SyncFileSnapshot,
    discovered_files: dict[str, Path],
    directory_name: str,
) -> RemoteInventory:
    guard = (
        (lambda path: guard_legacy_file(root, path))
        if directory_name == LEGACY_TRANSFER_CONVERSATIONS_DIRNAME
        else (lambda path: guard_task_file(root, path))
    )
    return reconcile_remote_discovery(
        root,
        persisted,
        index_snapshot,
        discovered_files,
        guard,
        directory_name=directory_name,
        format_version=persisted.format_version,
        propagate_io_errors=(
            persisted.format_version
            == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION
        ),
    )


def _v3_jsonl_files(files: dict[str, Path]) -> dict[str, Path]:
    return {
        relative_path: path
        for relative_path, path in files.items()
        if path.suffix == ".jsonl"
    }
