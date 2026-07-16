import codex_usage.sync as sync_module


def test_sync_package_exports_only_v2_models_and_runner_contract() -> None:
    assert sync_module.__all__ == [
        "Direction",
        "LocalInventory",
        "LocalSyncState",
        "ProjectBinding",
        "ProjectDestination",
        "ProjectIdentityKind",
        "ProjectResolutionRequest",
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
        "directional_blockers",
        "load_sync_selection_inventory",
        "pull_sync",
        "push_sync",
        "sync_status",
    ]
    assert not hasattr(sync_module, "export_threads")
    assert not hasattr(sync_module, "import_threads")
    assert not hasattr(sync_module, "plan_sync")
    assert not hasattr(sync_module, "list_threads")
    assert not hasattr(sync_module, "SYNC_VERSION")
    assert sync_module.ProjectBinding.__name__ == "ProjectBinding"
    assert sync_module.ProjectDestination.__name__ == "ProjectDestination"
