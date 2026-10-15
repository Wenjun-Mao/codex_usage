"""Canonical physical ownership for cached facts, including page mirrors."""
import json
from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_history import PAGE_KEY_PREFIX, source_identity
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_rollout_identity import rollout_identity
from codex_usage.replica_accounting_selection import accounting_predicate, selected_sql

_IDENTITY_PREFIX = "paginated-physical:"


def record_physical_identity(connection, checkpoint):
    metadata = checkpoint.state.root_metadata
    if metadata is None or metadata.history_mode != "paginated":
        return
    try:
        key = source_identity(metadata)
    except PaginatedHistoryError:
        return
    physical = rollout_identity(metadata.file_path)
    if checkpoint.session_id != metadata.session_id:
        return
    # Identity evidence outlives the replaceable resume artifact. It declares
    # membership only, not financial validity or authority to resume parsing.
    connection.execute("insert or ignore into schema_meta(key,value) values (?,?)",
        (_IDENTITY_PREFIX+physical.rollout_id, json.dumps(dict(version=1,
            physical_id=physical.rollout_id, logical_id=metadata.session_id, canonical_key=key), sort_keys=True)))


def known_physical_identity(connection, physical_id):
    row = connection.execute("select value from schema_meta where key=?", (_IDENTITY_PREFIX+physical_id,)).fetchone()
    return json.loads(row[0]) if row is not None else None


def owner_predicate(alias="files"):
    if alias not in {"files", "f"}:
        raise ValueError("Unsupported source-owner table alias")
    canonical = f"({alias}.file_key = {alias}.session_id or {alias}.file_key glob '{PAGE_KEY_PREFIX}*')"
    return f"(({canonical} and {accounting_predicate(alias)}) or {alias}.file_key in ({selected_sql()}))"


def cached_source_identity(connection, entry, cached):
    if cached is None or not cached["session_id"]:
        return ""
    logical = str(cached["session_id"])
    if connection.execute("""select 1 from session_metadata
        where file_key=? and session_id=? and is_missing=0""", (entry.file_key, logical)).fetchone() is None:
        return ""
    physical = rollout_identity(entry.path)
    if physical is None or physical.rollout_id == physical.thread_id:
        return logical
    checkpoint = load_parser_checkpoint(connection, entry.file_key, entry.path)
    metadata = checkpoint.state.root_metadata if checkpoint is not None else None
    # Old checkpoints did not retain page metadata. They need bounded discovery,
    # not promotion of a physical page into its logical root's ownership slot.
    if (metadata is None or metadata.history_mode != "paginated"
            or checkpoint.session_id != logical or metadata.session_id != logical):
        return ""
    try:
        return source_identity(metadata)
    except PaginatedHistoryError:
        return ""
