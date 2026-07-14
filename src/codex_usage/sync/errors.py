from __future__ import annotations


class SyncStoreError(Exception):
    """Base error for typed sync-store failures."""


class LegacySyncLayoutError(SyncStoreError):
    """The selected folder contains an unsupported legacy sync layout."""


class MalformedSyncIndexError(SyncStoreError):
    """The remote sync index does not satisfy the version-2 contract."""


class MissingRemoteConversationError(SyncStoreError):
    """An indexed remote conversation is missing."""


class ConcurrentLocalChangeError(SyncStoreError):
    """A local conversation changed after planning."""


class ConcurrentRemoteChangeError(SyncStoreError):
    """A remote conversation or index entry changed after planning."""
