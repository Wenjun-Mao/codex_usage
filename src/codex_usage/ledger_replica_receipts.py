"""Normalize pre-parse replica proofs without reopening historical files."""
from datetime import UTC, datetime
import json

from codex_usage.session_replica_retention import ALIAS_PREFIX


def retire_proven_replica_generations(connection):
    changed = False
    for row in connection.execute("select value from schema_meta where key like ?", (ALIAS_PREFIX+"%",)).fetchall():
        receipt = json.loads(row[0])
        if receipt.get("retired") is True:
            continue
        owner = connection.execute("""select f.*, c.byte_offset, c.head_sha256, c.boundary_sha256,
                cast(c.source_device as text) source_device, cast(c.source_inode as text) source_inode
            from files f join parser_checkpoints c using(file_key)
            where file_key=? and f.is_missing=0 and coalesce(f.error,'')=''""", (receipt["owner_key"],)).fetchone()
        snapshot = receipt["owner_snapshot"]
        if owner is None or any(owner[key] != value for key, value in snapshot.items()):
            continue
        replacement = connection.execute("""select g.* from ledger_generations g
            join ledger_sources s using(source_id) where s.source_key=? and g.status='trusted'
            and g.captured_size=? and g.head_sha256=? and g.boundary_sha256=?""",
            (receipt["owner_key"], owner["byte_offset"], owner["head_sha256"], owner["boundary_sha256"])).fetchone()
        if replacement is None:
            continue
        prefixes = receipt["prefixes"]
        if owner["byte_offset"] < max(p["byte_offset"] for p in prefixes):
            continue
        for old in connection.execute("""select g.* from ledger_generations g
            join ledger_sources s using(source_id) where s.source_key=? and g.status='trusted'""",
            (receipt["mirror_key"],)).fetchall():
            if not any((p["byte_offset"], p["head_sha256"], p["boundary_sha256"]) == (
                    old["captured_size"], old["head_sha256"], old["boundary_sha256"]) for p in prefixes):
                continue
            connection.execute("update ledger_generations set status='superseded', completed_at=? where generation_id=?",
                (datetime.now(UTC).isoformat(), old["generation_id"]))
            connection.execute("insert or ignore into ledger_meta(key,value) values (?,?)",
                (f"source-mirror:{old['generation_id']}", json.dumps(dict(receipt,
                    old_generation_id=old["generation_id"], owner_generation_id=replacement["generation_id"]), sort_keys=True)))
            changed = True
        unresolved = connection.execute("""select 1 from ledger_generations g
            join ledger_sources s using(source_id) where s.source_key=? and g.status='trusted'""",
            (receipt["mirror_key"],)).fetchone()
        if unresolved is None and receipt.get("retired") is not True:
            receipt["retired"] = True
            connection.execute("update schema_meta set value=? where key=?",
                (json.dumps(receipt, sort_keys=True), ALIAS_PREFIX+receipt["mirror_key"]))
    return changed
