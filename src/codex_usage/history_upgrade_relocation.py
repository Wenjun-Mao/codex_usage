"""Byte-proven alternate inputs for replay; never move a retained checkpoint."""
import hashlib
import json
from pathlib import Path

from codex_usage.session_history import HISTORY_PREFIX_LIMIT
from codex_usage.session_parser_safety import CapturedPrefix
from codex_usage.session_replica_guards import (
    ReplicaEvidenceError, ReplicaReadBudget, capture_prefix, prefix_width, prove_prefixes,
)
from codex_usage.session_rollout_identity import rollout_identity

PREFIX = "history-upgrade-relocation:"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _capture(connection, key):
    row = connection.execute("""select f.path, f.session_id, f.parsed_at, p.*
        from files f join parser_checkpoints p using(file_key) where f.file_key=?""", (key,)).fetchone()
    if row is None or not row["session_id"] or int(row["byte_offset"]) <= 0:
        return None
    normalized = []
    if connection.execute("select 1 from sqlite_master where name='ledger_generations'").fetchone():
        normalized = [dict(member) for member in connection.execute("""select g.generation_id,
            g.captured_size, g.head_sha256, g.boundary_sha256, g.record_count
            from ledger_generations g join ledger_sources s using(source_id)
            where s.source_key=? and g.status!='superseded' order by g.generation_id""", (key,))]
    prefixes = [CapturedPrefix(row["byte_offset"], row["head_sha256"], row["boundary_sha256"])]
    prefixes.extend(CapturedPrefix(g["captured_size"], g["head_sha256"], g["boundary_sha256"]) for g in normalized)
    if any(p.byte_offset <= 0 or len(p.head_sha256) != 64 or len(p.boundary_sha256) != 64 for p in prefixes):
        return None
    return _digest((dict(row), normalized)), tuple(dict.fromkeys(prefixes))


def _entry_facts(entry):
    stat = entry.path.stat()
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != (
            entry.source_device, entry.source_inode, entry.size_bytes, entry.mtime_ns):
        raise ReplicaEvidenceError("paginated_history_replica_source_changed")
    return dict(path=str(entry.path), session_dir=str(entry.session_dir), storage_state=entry.storage_state,
                size_bytes=entry.size_bytes, mtime_ns=entry.mtime_ns, source_device=entry.source_device,
                source_inode=entry.source_inode, ctime_ns=stat.st_ctime_ns)


def _receipt(connection, key):
    row = connection.execute("select value from schema_meta where key=?", (PREFIX+key,)).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        entry = value["entry"]
        if (type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["capture"], str) or len(value["capture"]) != 64
                or not isinstance(value["candidates"], list) or not value["candidates"]
                or entry not in value["candidates"] or not all(_valid_entry(member) for member in value["candidates"])):
            return None
        return value
    except (ValueError, TypeError, KeyError):
        return None


def _valid_entry(entry):
    return (all(isinstance(entry[n], str) for n in ("path", "session_dir", "storage_state"))
            and all(type(entry[n]) is int and entry[n] >= 0 for n in (
                "size_bytes", "mtime_ns", "source_device", "source_inode", "ctime_ns"))
            and Path(entry["path"]).is_absolute()
            and Path(entry["path"]).is_relative_to(Path(entry["session_dir"])))


def qualify_relocation(connection, key, row, inventory, *, max_bytes, max_files, batch_bytes, batch_files, inspect):
    """Return (diagnostic, consumed bytes, attempted files); no financial writes."""
    physical = rollout_identity(Path(row["path"]))
    entries = [entry for entry in inventory if physical is not None
        and (identity := rollout_identity(entry.path)) is not None
        and identity.rollout_id == physical.rollout_id and str(entry.path) != row["path"]]
    if not entries:
        return "unavailable", 0, 0
    capture = _capture(connection, key)
    if capture is None:
        return "unavailable", 0, 0
    entries.sort(key=lambda e: (-e.size_bytes, str(e.path).casefold()))
    winner = entries[0]
    budget = ReplicaReadBudget(max_bytes)
    try:
        facts = [_entry_facts(entry) for entry in entries]
        previous = _receipt(connection, key)
        if previous and previous["capture"] == capture[0] and previous["candidates"] == facts:
            return "qualified", 0, 0
        limit = max(1, min(HISTORY_PREFIX_LIMIT, winner.size_bytes))
        estimate = limit+1+sum(prefix_width(e.size_bytes) for e in entries[1:])*2
        estimate += sum(prefix_width(p.byte_offset) for p in capture[1])
        if len(entries) > batch_files or estimate > batch_bytes:
            return "relocation_exceeds_discovery_budget", 0, 0
        if len(entries) > max_files or estimate > max_bytes:
            return "budget", 0, 0
        budget.reserve(limit+1)
        kind, reason, diagnostic, consumed = inspect(winner, row, limit)
        budget.bytes_read += consumed
        if kind == "pending":
            return str(reason), budget.bytes_read, len(entries)
        prefixes = [capture_prefix(entry, budget) for entry in entries[1:]]
        prove_prefixes(winner, (*capture[1], *prefixes), budget)
        if facts != [_entry_facts(entry) for entry in entries]:
            raise ReplicaEvidenceError("paginated_history_replica_source_changed")
        value = dict(version=1, capture=capture[0], entry=facts[0], candidates=facts)
        connection.execute("insert or replace into schema_meta(key,value) values (?,?)",
                           (PREFIX+key, json.dumps(value, sort_keys=True)))
        return "qualified", budget.bytes_read, len(entries)
    except OSError:
        return "unavailable", budget.bytes_read, min(len(entries), max_files)
    except ReplicaEvidenceError as error:
        return str(error), budget.bytes_read, min(len(entries), max_files)


def relocated_source(connection, key, source):
    receipt = _receipt(connection, key)
    capture = _capture(connection, key)
    if receipt is None or capture is None or receipt["capture"] != capture[0]:
        return None
    entry = receipt["entry"]
    return {**dict(source), "captured_path": source["path"], "path": entry["path"],
            "session_dir": entry["session_dir"], "storage_state": entry["storage_state"],
            "recovery_id": _digest(receipt), "recovery_snapshots": receipt["candidates"]}


def assert_relocation_snapshot(source):
    if "recovery_snapshots" not in dict(source):
        return
    for entry in source["recovery_snapshots"]:
        stat = Path(entry["path"]).stat()
        if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != tuple(
                entry[n] for n in ("source_device", "source_inode", "size_bytes", "mtime_ns", "ctime_ns")):
            raise OSError("rebuild relocation source changed; ordinary capture must qualify it again")


def clear_relocation(connection, key):
    connection.execute("delete from schema_meta where key=?", (PREFIX+key,))
