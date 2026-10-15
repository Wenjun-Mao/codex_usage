"""Bind staging to its captured owner, independently of replaceable checkpoints."""
import hashlib
import json
from pathlib import Path

from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_history import source_identity
from codex_usage.session_parser_models import parser_state_to_json


class StagedCaptureUnavailableError(RuntimeError):
    """A fresh ordinary capture may make the staged source readable again."""


def load_rebuild_source(connection, source_key):
    return connection.execute("""select s.source_key, s.path, s.session_dir, s.storage_state,
        f.session_id, f.parsed_at, p.byte_offset, p.next_record_index,
        p.head_sha256, p.boundary_sha256, p.source_device, p.source_inode, p.state_json,
        coalesce((select value from schema_meta where key='history-invalidation:'||s.source_key),'0') history_epoch
        from ledger_sources s join files f on f.file_key=s.source_key and f.path=s.path
        left join parser_checkpoints p on p.file_key=f.file_key
        where s.source_key=? and s.is_stale=1 and s.is_missing=0""", (source_key,)).fetchone()


def _origin(source):
    if source is None or not source["session_id"]:
        raise RuntimeError("staged capture identity lacks a captured owner")
    fields = dict(source)
    state = fields.pop("state_json")
    fields["state_digest"] = hashlib.sha256((state or "").encode()).hexdigest()
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def bind_rebuild_authority(connection, source):
    connection.execute("""create table if not exists rebuild_authority (
        id integer primary key check(id=1), authority_json text not null)""")
    origin = _origin(source)
    row = connection.execute("select authority_json from rebuild_authority where id=1").fetchone()
    if row is not None:
        authority = json.loads(row[0])
        if authority.get("version") != 1 or authority.get("origin") != origin:
            raise RuntimeError("staged capture identity changed from its authorized owner")
        if authority["header"] is None and _table_exists(connection, "parser_checkpoints"):
            rows = connection.execute("select file_key, path from files where path=?", (source["path"],)).fetchall()
            if len(rows) > 1:
                raise RuntimeError("staged capture identity has ambiguous saved ownership")
            for member in rows:
                checkpoint = load_parser_checkpoint(connection, member["file_key"], Path(member["path"]))
                if checkpoint is not None:
                    _capture_header(connection, member["file_key"], checkpoint, authority)
                elif connection.execute("select 1 from parser_checkpoints where file_key=?", (member["file_key"],)).fetchone():
                    raise RuntimeError("staged capture identity has an invalid saved checkpoint")
        return authority
    if any(_table_exists(connection, table) and connection.execute(f"select 1 from {table} limit 1").fetchone()
           for table in ("files", "parser_checkpoints", "usage_records")):
        raise RuntimeError("staged capture identity has no originating authority")
    authority = dict(version=1, origin=origin, logical_id=source["session_id"], header=None)
    connection.execute("insert into rebuild_authority values (1,?)", (json.dumps(authority, sort_keys=True),))
    connection.commit()
    return authority


def _table_exists(connection, table):
    return connection.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone() is not None


def _capture_header(connection, file_key, checkpoint, authority):
    metadata = checkpoint.state.root_metadata
    if metadata is None:
        return False
    if (metadata.session_id != authority["logical_id"]
            or checkpoint.session_id != authority["logical_id"]
            or source_identity(metadata) != file_key):
        raise RuntimeError("staged capture identity changed from its authorized owner")
    header = json.loads(parser_state_to_json(checkpoint.state))["root_metadata"]
    if authority["header"] is None:
        authority["header"] = header
        connection.execute("update rebuild_authority set authority_json=? where id=1",
                           (json.dumps(authority, sort_keys=True),))
        connection.commit()
    elif authority["header"] != header:
        raise RuntimeError("staged capture identity changed during rebuild")
    return True


def validate_staged_capture(connection, entry, checkpoint, authority):
    if checkpoint is None:
        return False
    row = connection.execute("select * from files where file_key=?", (entry.file_key,)).fetchone()
    if row is None or row["error"] or row["is_missing"]:
        raise StagedCaptureUnavailableError("staged capture is unavailable or has a parse error")
    if not _capture_header(connection, entry.file_key, checkpoint, authority):
        return False
    if (row["path"] != str(entry.path) or row["size_bytes"] != entry.size_bytes
            or row["mtime_ns"] != entry.mtime_ns
            or (checkpoint.source_device, checkpoint.source_inode) != (entry.source_device, entry.source_inode)):
        raise RuntimeError("staged capture does not match the current source snapshot")
    return not checkpoint.state.row_drain


def assert_live_rebuild_authority(connection, source_key, authority):
    if _origin(load_rebuild_source(connection, source_key)) != authority["origin"]:
        raise RuntimeError("staged capture identity changed before installation")


def assert_attached_stage(connection, entry, checkpoint):
    row = connection.execute("""select p.*, f.path, f.error, f.is_missing,
        f.size_bytes, f.mtime_ns from rebuild.files f
        join rebuild.parser_checkpoints p using(file_key) where f.file_key=?""", (entry.file_key,)).fetchone()
    expected = dict(byte_offset=checkpoint.byte_offset,
        next_record_index=checkpoint.next_record_index,
        next_candidate_index=checkpoint.next_candidate_index,
        source_device=str(checkpoint.source_device), source_inode=str(checkpoint.source_inode),
        head_sha256=checkpoint.head_sha256, boundary_sha256=checkpoint.boundary_sha256,
        session_id=checkpoint.session_id, state_json=parser_state_to_json(checkpoint.state),
        path=str(entry.path), size_bytes=entry.size_bytes, mtime_ns=entry.mtime_ns)
    if (row is None or row["error"] or row["is_missing"]
            or any(row[key] != value for key, value in expected.items())):
        raise RuntimeError("staged capture changed before installation")


def assert_installed_authority(connection, entry, checkpoint):
    row = connection.execute("""select g.* from ledger_generations g
        join ledger_sources s using(source_id)
        where s.source_key=? and s.path=? and s.is_stale=0 and s.is_missing=0
          and g.status='trusted'""", (entry.file_key, str(entry.path))).fetchone()
    expected = (checkpoint.byte_offset, checkpoint.next_record_index,
                checkpoint.head_sha256, checkpoint.boundary_sha256)
    if row is None or tuple(row[key] for key in (
            "captured_size", "record_count", "head_sha256", "boundary_sha256")) != expected:
        raise RuntimeError("staged capture did not establish replacement accounting authority")
