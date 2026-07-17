from __future__ import annotations


class SyncStoreError(Exception):
    """Base error for typed sync-store failures."""


class LegacySyncLayoutError(SyncStoreError):
    """The selected folder contains an unsupported legacy sync layout."""


class MalformedSyncIndexError(SyncStoreError):
    """The remote sync index does not satisfy the current transfer contract."""


class TransferFormatMigrationError(SyncStoreError):
    """The remote transfer folder cannot be migrated without risking data loss."""


class TransferFilesystemError(SyncStoreError):
    """A filesystem failure interrupted transfer execution."""

    def __init__(
        self,
        error: OSError,
        *,
        pulled_thread_ids: tuple[str, ...] = (),
        pushed_thread_ids: tuple[str, ...] = (),
    ) -> None:
        detail = str(error).strip() or type(error).__name__
        super().__init__(f"Task transfer filesystem operation failed: {detail}")
        self.pulled_thread_ids = pulled_thread_ids
        self.pushed_thread_ids = pushed_thread_ids


class MissingRemoteConversationError(SyncStoreError):
    """An indexed remote task is missing."""


class ConcurrentLocalChangeError(SyncStoreError):
    """A local task changed after planning."""


class ConcurrentRemoteChangeError(SyncStoreError):
    """A remote task or index entry changed after planning."""
