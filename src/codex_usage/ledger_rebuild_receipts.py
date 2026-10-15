"""Preserve replaced accounting evidence when a complete staged rebuild wins."""
from datetime import UTC, datetime
import hashlib
import json


def supersede_rebuilt_generations(connection, source_key, replacement_key, checkpoint, authority):
    rows = connection.execute("""select g.* from ledger_generations g
        join ledger_sources s using(source_id)
        where s.source_key=? and g.status='trusted'""", (source_key,)).fetchall()
    metadata = checkpoint.state.root_metadata
    if (metadata is not None and metadata.history_mode == "paginated"
            and any(row["captured_size"] > checkpoint.byte_offset for row in rows)):
        raise RuntimeError("rebuilt paginated source does not cover retained capture")
    now = datetime.now(UTC).isoformat()
    for row in rows:
        connection.execute("""update ledger_generations
            set status='superseded', completed_at=? where generation_id=?""",
            (now, row["generation_id"]))
        connection.execute("insert into ledger_meta(key,value) values (?,?)", (
            f"source-rebuild:{row['generation_id']}",
            json.dumps(dict(version=1, source_key=source_key,
                replacement_key=replacement_key, previous=dict(row),
                origin_fingerprint=authority["origin"],
                header_fingerprint=hashlib.sha256(json.dumps(authority["header"], sort_keys=True).encode()).hexdigest(),
                history_boundary_digest=checkpoint.state.history_boundary_digest,
                captured_size=checkpoint.byte_offset, head_sha256=checkpoint.head_sha256,
                boundary_sha256=checkpoint.boundary_sha256), sort_keys=True),
        ))
