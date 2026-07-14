import codex_usage.sync as sync_module


def test_sync_package_exports_only_v2_models_and_runner_contract() -> None:
    assert sync_module.__all__ == [
        "LocalInventory",
        "LocalSyncState",
        "RemoteIndex",
        "RemoteInventory",
        "RemoteThreadEntry",
        "SyncCounts",
        "SyncFileSnapshot",
        "SyncIssue",
        "SyncPlan",
        "SyncPlanItem",
        "SyncProgressEvent",
        "SyncProjectInventoryItem",
        "SyncRunResult",
        "SyncSelectionInventory",
        "SyncTaskInventoryItem",
        "SyncTimings",
        "build_sync_selection_inventory",
        "load_sync_selection_inventory",
        "run_sync",
        "sync_status",
    ]
    assert not hasattr(sync_module, "export_threads")
    assert not hasattr(sync_module, "import_threads")
    assert not hasattr(sync_module, "plan_sync")
    assert not hasattr(sync_module, "list_threads")
    assert not hasattr(sync_module, "SYNC_VERSION")
