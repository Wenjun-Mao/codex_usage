from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_usage.sync.store as sync_store
from codex_usage.sync.errors import (
    LegacySyncLayoutError,
    SyncStoreError,
    TransferFormatMigrationError,
)
from codex_usage.sync.store import RemoteStore


def test_transfer_format_migration_error_uses_store_error_contract() -> None:
    assert issubclass(TransferFormatMigrationError, SyncStoreError)


def test_load_inventory_migrates_while_transaction_is_held(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RemoteStore(tmp_path / "sync")
    lock_states: list[bool] = []

    def observe_lock(_root: Path) -> None:
        lock_states.append(store._lock.is_locked)

    monkeypatch.setattr(sync_store, "migrate_remote_layout_v2_to_v3", observe_lock)

    store.load_inventory()

    assert lock_states == [True]
    assert not store._lock.is_locked


def test_load_inventory_reuses_existing_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RemoteStore(tmp_path / "sync")
    outer_transaction = store.transaction
    lock_states: list[bool] = []

    def observe_lock(_root: Path) -> None:
        lock_states.append(store._lock.is_locked)

    def unexpected_nested_transaction():
        raise AssertionError("load_inventory must reuse the held transaction")

    monkeypatch.setattr(sync_store, "migrate_remote_layout_v2_to_v3", observe_lock)
    with outer_transaction():
        monkeypatch.setattr(store, "transaction", unexpected_nested_transaction)
        store.load_inventory()

    assert lock_states == [True]
    assert not store._lock.is_locked


def test_load_inventory_reports_version_1_index_as_legacy_without_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    root.mkdir()
    index_path = root / "sync-index.json"
    contents = (
        json.dumps({"format_version": 1, "updated_at": "", "threads": {}}) + "\n"
    ).encode()
    index_path.write_bytes(contents)

    with pytest.raises(LegacySyncLayoutError):
        RemoteStore(root).load_inventory()

    assert index_path.read_bytes() == contents
