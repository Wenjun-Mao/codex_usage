"""Retained parser generations and content-free physical-replica receipts."""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_history import source_identity
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_parser_safety import CapturedPrefix
from codex_usage.session_rollout_identity import rollout_identity
from codex_usage.session_parser_models import SessionParseCheckpoint
from codex_usage.replica_accounting_selection import accounting_keys

ALIAS_PREFIX = "physical-replica-alias:"


@dataclass(frozen=True, slots=True)
class RetainedReplica:
    row: sqlite3.Row
    checkpoint: SessionParseCheckpoint
    prefixes: tuple[CapturedPrefix, ...]


def cached_replica_families(cached_rows):
    groups = {}
    for key, row in cached_rows.items():
        identity = rollout_identity(Path(row["path"]))
        if identity is not None:
            groups.setdefault(identity.rollout_id, {})[key] = row
    return groups


def retained_family_state(connection, physical_id, cached_rows):
    family = []
    normalized = connection.execute("select 1 from sqlite_master where name='ledger_generations'").fetchone()
    for row in cached_rows.values():
        path = Path(row["path"])
        identity = rollout_identity(path)
        if identity is None or identity.rollout_id != physical_id:
            continue
        checkpoint = load_parser_checkpoint(connection, row["file_key"], path)
        metadata = checkpoint.state.root_metadata if checkpoint else None
        if metadata is None or metadata.history_mode != "paginated":
            continue
        try:
            key = source_identity(metadata)
        except PaginatedHistoryError:
            continue
        if metadata.session_id != checkpoint.session_id or checkpoint.session_id != row["session_id"]:
            continue
        prefixes = [CapturedPrefix(checkpoint.byte_offset, checkpoint.head_sha256, checkpoint.boundary_sha256)]
        if normalized:
            for generation in connection.execute("""select g.* from ledger_generations g
                join ledger_sources s using(source_id) where s.source_key=? and g.status='trusted'""",
                (row["file_key"],)):
                prefixes.append(CapturedPrefix(generation["captured_size"], generation["head_sha256"],
                                               generation["boundary_sha256"]))
        family.append((key, RetainedReplica(row, checkpoint, tuple(dict.fromkeys(prefixes)))))
    return family


def pending_aliases(connection):
    groups = {}
    for row in connection.execute("select value from schema_meta where key like ?", (ALIAS_PREFIX+"%",)):
        receipt = json.loads(row[0])
        if receipt.get("retired") is not True:
            groups.setdefault(receipt["owner_key"], []).append(receipt)
    return groups


def alias_prefixes(receipts):
    return tuple(dict.fromkeys(CapturedPrefix(**prefix) for receipt in receipts for prefix in receipt["prefixes"]))


def record_aliases(connection, winner, family, pending):
    owner_key = winner.file_key
    obligations = {r["mirror_key"]: list(alias_prefixes((r,))) for r in pending}
    for key, replica in family:
        mirror_key = replica.row["file_key"]
        if key != owner_key or mirror_key == owner_key:
            continue
        obligations.setdefault(mirror_key, []).extend(replica.prefixes)
    for mirror_key, prefixes in obligations.items():
        connection.execute("insert or replace into schema_meta(key,value) values (?,?)",
            (ALIAS_PREFIX+mirror_key, json.dumps(dict(owner_key=owner_key, mirror_key=mirror_key,
                version=1, retired=False,
                owner_snapshot=dict(path=str(winner.path), size_bytes=winner.size_bytes,
                    mtime_ns=winner.mtime_ns, source_device=str(winner.source_device),
                    source_inode=str(winner.source_inode)),
                prefixes=[dict(byte_offset=p.byte_offset, head_sha256=p.head_sha256,
                               boundary_sha256=p.boundary_sha256) for p in dict.fromkeys(prefixes)]), sort_keys=True)))


def accounted_keys(connection, selected_keys):
    """A proven physical mirror is not independent retained consumption."""
    excluded = set()
    for row in connection.execute("select value from schema_meta where key like ?", (ALIAS_PREFIX+"%",)):
        receipt = json.loads(row[0])
        if connection.execute("select 1 from files where file_key=?", (receipt["owner_key"],)).fetchone():
            excluded.add(receipt["mirror_key"])
    return accounting_keys(connection, selected_keys, excluded)
