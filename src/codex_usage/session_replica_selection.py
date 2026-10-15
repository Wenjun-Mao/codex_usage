"""Select a prefix-compatible physical replica before scheduling usage parsing."""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from codex_usage.session_cache_checkpoints import load_parser_checkpoint, upsert_parser_checkpoint
from codex_usage.session_cache_generations import rekey_file_generation
from codex_usage.session_cache_requests import load_cached_rows
from codex_usage.session_inventory import SessionFileInventoryEntry
from codex_usage.session_files import read_session_metadata_bounded
from codex_usage.session_history import PAGE_KEY_PREFIX, HISTORY_PREFIX_LIMIT, source_identity
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_replica_guards import (
    ReplicaEvidenceError, ReplicaReadBudget, capture_prefix, prefix_width, prove_prefixes,
)
from codex_usage.session_parser_safety import CapturedPrefix
from codex_usage.session_rollout_identity import rollout_identity
from codex_usage.session_replica_retention import (
    cached_replica_families, retained_family_state, record_aliases,
    pending_aliases, alias_prefixes,
)


@dataclass(frozen=True, slots=True)
class ReplicaSelection:
    blocked: dict[str, str]
    bytes_read: int
    affected_task_ids: frozenset[str]


def select_replicas(connection, inventory, cached_rows, *, max_bytes, protected_keys=frozenset()):
    """One parse source per physical ID; ordinary legacy ownership is unchanged."""
    groups = {}
    for entry in inventory:
        physical = rollout_identity(entry.path)
        if physical is not None:
            groups.setdefault(physical.rollout_id, []).append(entry)
    budget = ReplicaReadBudget(max_bytes)
    removed, replacements, blocked, affected = set(), {}, {}, set()
    connection.execute("begin immediate")
    try:
        cached_rows = load_cached_rows(connection)
        cached_families = cached_replica_families(cached_rows)
        obligations = pending_aliases(connection)
        for physical, entries in groups.items():
            hint = rollout_identity(entries[0].path)
            key_hint = hint.thread_id if hint.thread_id == physical else PAGE_KEY_PREFIX+physical
            if key_hint in protected_keys or any(entry.file_key in protected_keys for entry in entries):
                continue
            owner = cached_rows.get(key_hint)
            group_rows = cached_families.get(physical, {})
            pending = obligations.get(key_hint, ())
            # A lone unchanged path has no replica handoff to reconcile.
            if (len(entries) == 1 and not pending and not any(key != key_hint for key in group_rows)
                    and (owner is None or (str(entries[0].path) == owner["path"]
                    and "paginated_history_replica_" not in str(owner["error"] or "")))):
                continue
            family = retained_family_state(connection, physical, group_rows)
            paginated = bool(family)
            try:
                winner = _winner(entries, owner)
                canonical = replace(winner, file_key=key_hint, file_key_is_fallback=False)
                if _reusable_proof(connection, canonical, entries, owner, group_rows):
                    removed.update(entry.path for entry in entries)
                    replacements[canonical.path] = canonical
                    continue
                metadata = []
                for entry in entries:
                    member = _metadata(connection, entry, cached_rows, budget)
                    metadata.append(member)
                    paginated |= member is not None and member.history_mode == "paginated"
                if not paginated:
                    continue
                if any(m is None or m.history_mode != "paginated" for m in metadata):
                    raise ReplicaEvidenceError("paginated_history_replica_metadata_unavailable")
                keys = {source_identity(m) for m in metadata}
                if len(keys) != 1:
                    raise ReplicaEvidenceError("paginated_history_replica_identity_conflict")
                key = keys.pop()
                owner = cached_rows.get(key)
                winner = _winner(entries, owner)
                canonical = replace(winner, file_key=key, file_key_is_fallback=False)
                _select(connection, canonical, entries, owner, group_rows, family, pending, budget)
            except (ReplicaEvidenceError, PaginatedHistoryError) as error:
                if not paginated:
                    # Unclassified legacy files retain the normal bounded
                    # discovery path; a filename is not page-header authority.
                    continue
                # Keep the prior canonical facts and expose a named stale source.
                canonical = replace(entries[0], file_key=key_hint, file_key_is_fallback=False)
                blocked[key_hint] = "PaginatedHistoryError: "+str(error)
                connection.execute("update files set error=? where file_key=?",
                    (blocked[key_hint], key_hint))
            removed.update(entry.path for entry in entries)
            replacements[canonical.path] = canonical
            if owner is not None and owner["session_id"]:
                affected.add(str(owner["session_id"]))
            # A rekey can replace a legacy logical-owner slot. Later families
            # must pair checkpoints with current rows, not pre-transaction paths.
            cached_rows = load_cached_rows(connection)
            cached_families = cached_replica_families(cached_rows)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    inventory[:] = [replacements.get(e.path, e) for e in inventory
                    if e.path not in removed or e.path in replacements]
    return ReplicaSelection(blocked, budget.bytes_read, frozenset(affected))


def _metadata(connection, entry, cached_rows, budget):
    cached = cached_rows.get(entry.file_key)
    if (cached is not None and cached["path"] == str(entry.path)
            and cached["size_bytes"] == entry.size_bytes
            and cached["mtime_ns"] == entry.mtime_ns):
        checkpoint = load_parser_checkpoint(connection, entry.file_key, entry.path)
        if (checkpoint is not None and checkpoint.state.root_metadata is not None
                and (checkpoint.source_device, checkpoint.source_inode) == (
                    entry.source_device, entry.source_inode)):
            return checkpoint.state.root_metadata
    limit = max(1, min(HISTORY_PREFIX_LIMIT, entry.size_bytes))
    budget.reserve(limit+1)
    read = read_session_metadata_bounded(entry.path, max_bytes=limit)
    budget.bytes_read += read.bytes_read
    return read.metadata


def _winner(entries, owner):
    return min(entries, key=lambda e: (-e.size_bytes,
        0 if owner is not None and str(e.path) == owner["path"] else 1,
        0 if e.storage_state == "active" else 1, str(e.path).casefold()))


def _retained_prefixes(connection, winner, cached_rows, *, include_owner=True):
    required = []
    physical = rollout_identity(winner.path).rollout_id
    for row in cached_rows.values():
        if not include_owner and row["file_key"] == winner.file_key:
            continue
        identity = rollout_identity(Path(row["path"]))
        if identity is None or identity.rollout_id != physical:
            continue
        prior = load_parser_checkpoint(connection, row["file_key"], Path(row["path"]))
        if prior is not None:
            required.append(CapturedPrefix(prior.byte_offset, prior.head_sha256, prior.boundary_sha256))
    return required


def _reusable_proof(connection, winner, entries, owner, cached_rows):
    if owner is None or owner["error"] or owner["path"] != str(winner.path):
        return False
    checkpoint = load_parser_checkpoint(connection, winner.file_key, winner.path)
    if checkpoint is None or (checkpoint.source_device, checkpoint.source_inode) != (
            winner.source_device, winner.source_inode) or checkpoint.byte_offset > winner.size_bytes:
        return False
    metadata = checkpoint.state.root_metadata
    if metadata is None or metadata.history_mode != "paginated" or source_identity(metadata) != winner.file_key:
        return False
    receipt = connection.execute("select value from schema_meta where key=?",
        ("paginated-replica:"+winner.file_key,)).fetchone()
    return receipt is not None and receipt[0] == _signature(winner, entries,
        _retained_prefixes(connection, winner, cached_rows, include_owner=False))


def _select(connection, winner, entries, owner, cached_rows, family, pending, budget):
    checkpoint = (load_parser_checkpoint(connection, winner.file_key, Path(owner["path"]))
                  if owner is not None else None)
    if checkpoint is not None:
        metadata = checkpoint.state.root_metadata
        if metadata is None or metadata.history_mode != "paginated" or source_identity(metadata) != winner.file_key:
            raise ReplicaEvidenceError("paginated_history_replica_accounting_upgrade_required")
    required = [p for key, replica in family if key == winner.file_key for p in replica.prefixes]
    required.extend(alias_prefixes(pending))
    signature = _signature(winner, entries,
        _retained_prefixes(connection, winner, cached_rows, include_owner=False))
    receipt_key = "paginated-replica:"+winner.file_key
    receipt = connection.execute("select value from schema_meta where key=?", (receipt_key,)).fetchone()
    same_owner = (checkpoint is not None and owner["path"] == str(winner.path)
                  and checkpoint.source_device == winner.source_device and checkpoint.source_inode == winner.source_inode)
    if not (same_owner and receipt is not None and receipt[0] == signature):
        estimate = sum(prefix_width(e.size_bytes) for e in entries if e.path != winner.path)
        estimate += sum(prefix_width(p.byte_offset) for p in required)
        estimate += sum(prefix_width(e.size_bytes) for e in entries if e.path != winner.path)
        if estimate > budget.remaining:
            raise ReplicaEvidenceError("paginated_history_replica_read_budget")
        prefixes = [capture_prefix(entry, budget) for entry in entries if entry.path != winner.path]
        prove_prefixes(winner, (*prefixes, *required), budget)
    donors = [r for key, r in family if key == winner.file_key]
    donor = max(donors, key=lambda r: (r.checkpoint.byte_offset,
        r.row["file_key"] == winner.file_key), default=None)
    # A larger accounting-valid cached generation is adopted whole, never
    # reconstructed from token magnitudes or mixed with a shorter generation.
    if donor is not None and donor.row["file_key"] != winner.file_key:
        source = SessionFileInventoryEntry(path=Path(donor.row["path"]),
            session_dir=winner.session_dir, storage_state=winner.storage_state,
            size_bytes=donor.row["size_bytes"], mtime_ns=donor.row["mtime_ns"],
            file_key=donor.row["file_key"], file_key_is_fallback=True)
        rekey_file_generation(connection, source, winner)
        checkpoint = donor.checkpoint
        same_owner = False
    record_aliases(connection, winner, family, pending)
    if checkpoint is not None and not same_owner:
        # The proven byte prefix carries the full parser state to the new inode.
        rebound = replace(checkpoint, source_device=winner.source_device, source_inode=winner.source_inode)
        upsert_parser_checkpoint(connection, winner.file_key, rebound)
        connection.execute("""update files set path=?, session_dir=?, storage_state=?, size_bytes=?,
            mtime_ns=?, is_missing=0, missing_since=null, error='' where file_key=?""",
            (str(winner.path), str(winner.session_dir), winner.storage_state, winner.size_bytes,
             winner.mtime_ns, winner.file_key))
        connection.execute("""update session_metadata set file_path=?, session_dir=?, storage_state=?, is_missing=0
            where file_key=?""", (str(winner.path), str(winner.session_dir), winner.storage_state, winner.file_key))
    elif owner is not None and owner["error"] and "paginated_history_replica_" in owner["error"]:
        connection.execute("update files set error='' where file_key=?", (winner.file_key,))
    signature = _signature(winner, entries,
        _retained_prefixes(connection, winner, cached_rows, include_owner=False))
    connection.execute("insert or replace into schema_meta(key,value) values (?,?)", (receipt_key, signature))


def _signature(winner, entries, required):
    raw = [(str(e.path), e.size_bytes, e.mtime_ns, e.source_device, e.source_inode) for e in entries]
    # Advancing this owner's proven prefix cannot change an unchanged replica set.
    facts = [(p.byte_offset, p.head_sha256, p.boundary_sha256) for p in required]
    return hashlib.sha256(json.dumps((1, str(winner.path), sorted(raw), sorted(facts))).encode()).hexdigest()
