"""Owned physical-rollout identities and bounded inherited counter resolution."""
from dataclasses import dataclass
from pathlib import Path

from codex_usage.models import SessionMetadata, TokenUsage
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_rollout_identity import rollout_identity

HISTORY_READ_BUDGET = 2 * 1024 * 1024
HISTORY_PREFIX_LIMIT = 64 * 1024
HISTORY_TAIL_LIMIT = 256 * 1024
HISTORY_CHAIN_LIMIT = 32
PAGE_KEY_PREFIX = "codex-usage:page:"


@dataclass(frozen=True, slots=True)
class HistorySource:
    path: Path
    size_bytes: int
    source_device: int
    source_inode: int
    rollout_id_hint: str = ""

    @classmethod
    def from_inventory(cls, entry):
        identity = rollout_identity(entry.path)
        return cls(entry.path, entry.size_bytes, entry.source_device, entry.source_inode,
                   identity.rollout_id if identity else "")


@dataclass(frozen=True, slots=True)
class HistoryBaseline:
    usage: TokenUsage
    bytes_read: int
    boundary_digest: str


def source_identity(metadata: SessionMetadata) -> str:
    if metadata.history_mode != "paginated":
        return metadata.session_id
    identity = rollout_identity(metadata.file_path)
    if identity is None or identity.thread_id != metadata.session_id.lower():
        raise PaginatedHistoryError("paginated_rollout_identity_unavailable")
    return (metadata.session_id if identity.rollout_id == identity.thread_id
            else f"{PAGE_KEY_PREFIX}{identity.rollout_id}")


def validate_page_metadata(metadata):
    if metadata.history_mode != "paginated":
        if metadata.history_base is not None:
            raise PaginatedHistoryError("paginated_history_mode_mismatch")
        return
    source_identity(metadata)
    ordinal = metadata.history_base.end_ordinal_exclusive if metadata.history_base else 0
    if metadata.history_ordinal != ordinal:
        raise PaginatedHistoryError("paginated_history_metadata_ordinal_mismatch")


def inline_replay_possible(metadata):
    if metadata.history_mode != "paginated":
        return True
    identity = rollout_identity(metadata.file_path)
    return (metadata.history_base is None and identity.rollout_id == identity.thread_id
            and metadata.forked_from_ordinal_exclusive != 0)


def resolve_baseline(metadata: SessionMetadata, sources: tuple[HistorySource, ...]) -> HistoryBaseline:
    from codex_usage.session_history_resolver import resolve

    validate_page_metadata(metadata)
    if metadata.history_base is None:
        raise PaginatedHistoryError("paginated_history_reference_unavailable")
    return resolve(metadata, sources)
