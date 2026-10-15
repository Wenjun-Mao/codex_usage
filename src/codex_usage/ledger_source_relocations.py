"""Retire proven source-key aliases, not genuinely missing physical histories."""
from datetime import UTC, datetime
import json
from pathlib import Path

from codex_usage.session_parser_safety import matches_captured_prefix


def retire_relocated_generations(connection):
    rows = connection.execute("""
        select old.generation_id, old.source_id, old.head_sha256,
               old.captured_size old_size, old.boundary_sha256 old_boundary,
               alias.source_key old_key, owner.source_key owner_key,
               alias.path, alias.source_device, alias.source_inode,
               current.generation_id owner_generation_id
        from ledger_generations old
        join ledger_sources alias on alias.source_id=old.source_id
        join ledger_sources owner on owner.path=alias.path
            and owner.source_device=alias.source_device
            and owner.source_inode=alias.source_inode
            and owner.source_id!=alias.source_id
        join ledger_generations current on current.source_id=owner.source_id
            and current.status='trusted'
            and current.captured_size>=old.captured_size
        join files current_file on current_file.file_key=owner.source_key
            and current_file.path=owner.path
        join parser_checkpoints checkpoint on checkpoint.file_key=current_file.file_key
            and checkpoint.head_sha256=current.head_sha256
            and checkpoint.byte_offset=current.captured_size
            and checkpoint.boundary_sha256=current.boundary_sha256
            and cast(checkpoint.source_device as text)=owner.source_device
            and cast(checkpoint.source_inode as text)=owner.source_inode
        where old.status='trusted' and alias.is_missing=1
            and owner.is_missing=0 and owner.is_stale=0 and owner.error=''
            and alias.source_inode not in ('', '0')
            and alias.source_device not in ('', '0')
            and not exists (select 1 from files where file_key=alias.source_key)
        order by old.generation_id, current.generation_id
    """).fetchall()
    stamp = datetime.now(UTC).isoformat()
    retired = False
    for row in rows:
        if not matches_captured_prefix(Path(row["path"]), source_device=int(row["source_device"]),
                source_inode=int(row["source_inode"]), byte_offset=int(row["old_size"]),
                head_sha256=row["head_sha256"], boundary_sha256=row["old_boundary"]):
            continue
        connection.execute("""update ledger_generations set status='superseded', completed_at=?
            where generation_id=? and status='trusted'""", (stamp, row["generation_id"]))
        # Retain the old facts plus a content-free reason for their retirement.
        # Missing files with no proven same-physical-source owner are untouched.
        connection.execute("insert or ignore into ledger_meta(key,value) values (?,?)", (
            f"source-key-relocation:{row['generation_id']}",
            json.dumps(dict(row), sort_keys=True),
        ))
        retired = True
    return retired
