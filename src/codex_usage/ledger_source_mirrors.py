"""Normalize proven page mirrors once, without discarding spent branches."""
from datetime import UTC, datetime
import json
from pathlib import Path

from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_history import PAGE_KEY_PREFIX, source_identity
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_parser_safety import CapturedPrefix, matches_captured_prefixes


def skip_proven_page_mirror(connection, row, rows_by_key):
    key = row["file_key"]
    if key == row["session_id"] or key.startswith(PAGE_KEY_PREFIX) or row["error"] or row["is_missing"]:
        return False, False
    checkpoint = load_parser_checkpoint(connection, key, Path(row["path"]))
    metadata = checkpoint.state.root_metadata if checkpoint else None
    if (metadata is None or metadata.history_mode != "paginated"
            or checkpoint.session_id != row["session_id"] or metadata.session_id != row["session_id"]):
        return False, False
    try:
        owner_key = source_identity(metadata)
    except PaginatedHistoryError:
        return False, False
    if not owner_key.startswith(PAGE_KEY_PREFIX):
        return False, False
    owner = rows_by_key.get(owner_key)
    if owner is None or owner["error"] or owner["is_missing"] or owner["byte_offset"] is None:
        return False, False
    owner_checkpoint = load_parser_checkpoint(connection, owner_key, Path(owner["path"]))
    owner_metadata = owner_checkpoint.state.root_metadata if owner_checkpoint else None
    try:
        if (owner_metadata is None or owner_metadata.history_mode != "paginated"
                or source_identity(owner_metadata) != owner_key
                or owner_metadata.session_id != metadata.session_id):
            return False, False
    except PaginatedHistoryError:
        return False, False
    old = connection.execute("""select g.* from ledger_generations g join ledger_sources s using(source_id)
        where s.source_key=? and g.status='trusted'""", (key,)).fetchone()
    prefixes = (CapturedPrefix(checkpoint.byte_offset, checkpoint.head_sha256, checkpoint.boundary_sha256),)
    if old is not None:
        prefixes += (CapturedPrefix(old["captured_size"], old["head_sha256"], old["boundary_sha256"]),)
    if (owner["byte_offset"] < max(p.byte_offset for p in prefixes)
            or not matches_captured_prefixes(Path(owner["path"]), prefixes=prefixes,
            source_device=int(owner["source_device"]), source_inode=int(owner["source_inode"]),
            )):
        return False, False
    if old is None:
        return True, False
    connection.execute("update ledger_generations set status='superseded', completed_at=? where generation_id=?",
                       (datetime.now(UTC).isoformat(), old["generation_id"]))
    connection.execute("insert or ignore into ledger_meta(key,value) values (?,?)", (
        f"source-mirror:{old['generation_id']}", json.dumps(dict(owner_key=owner_key, mirror_key=key,
            generation_id=old["generation_id"], captured_size=old["captured_size"], head_sha256=old["head_sha256"],
            boundary_sha256=old["boundary_sha256"]), sort_keys=True)))
    return True, True
