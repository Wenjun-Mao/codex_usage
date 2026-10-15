"""Bounded retrospective header discovery before any cache ownership changes."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path

from codex_usage.checkpoint_history_contract import history_contract_sql
from codex_usage.history_upgrade_receipts import (
    WAIT_PREFIX, WAIT_ERROR, UpgradeDiscovery, UpgradeDisposition as Disposition,
    UpgradeReason as Reason, decision, store_decision,
)
from codex_usage.session_cache_store import record_file_stale
from codex_usage.session_cache_source_identity import cached_source_identity
from codex_usage.session_files import read_session_metadata_stream
from codex_usage.session_history import HISTORY_PREFIX_LIMIT, PAGE_KEY_PREFIX, source_identity, validate_page_metadata
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_rollout_identity import rollout_identity

DISCOVERY_BYTES = 1024 * 1024
DISCOVERY_FILES = 32
PENDING_ERROR = "accounting_upgrade_discovery_pending"
REBUILD_ERROR = "paginated_history_accounting_upgrade_required"


def discover_accounting_upgrades(connection, inventory, *, max_bytes=DISCOVERY_BYTES, max_files=DISCOVERY_FILES,
                                 protected_keys=frozenset()):
    if max_bytes < 0 or max_files < 0:
        raise ValueError("discovery budgets cannot be negative")
    rows = connection.execute(f"""select f.file_key, f.path, f.session_id,
        p.byte_offset, p.next_record_index, p.head_sha256, p.boundary_sha256,
        p.session_id checkpoint_session_id from files f join parser_checkpoints p using(file_key)
        where not coalesce(({history_contract_sql()}),0)""").fetchall()
    old = {str(row["file_key"]): row for row in rows}
    candidates = []
    decisions = {}
    matched = set()
    for entry in inventory:
        row = old.get(entry.file_key)
        if row is None or row["path"] != str(entry.path):
            continue
        matched.add(entry.file_key)
        previous = decision(connection, entry.file_key)
        guard = _signature(entry, row)
        if previous and previous.get("guard") == guard and previous["disposition"] != Disposition.PENDING:
            decisions[entry.file_key] = previous
        else:
            attempt = previous.get("attempt", 0) if previous else 0
            candidates.append((0 if not attempt else 1,
                -entry.mtime_ns if not attempt else attempt, entry.file_key, entry, row, guard, previous))
    candidates.sort(key=lambda item: item[:3])
    absent = {key for key in old.keys()-matched if not _retired_capture(connection, key)}
    protected = set(protected_keys) | absent | {key for key, value in decisions.items() if value["disposition"] != Disposition.UNCHANGED}
    waiting = connection.execute("select 1 from schema_meta where key like ? limit 1", (WAIT_PREFIX+"%",)).fetchone()
    if not candidates and not protected and waiting is None:
        return UpgradeDiscovery(frozenset(), 0)
    sequence = _sequence(connection)
    bytes_read = attempted = reserved = 0
    connection.execute("begin immediate")
    try:
        for _, _, key, entry, row, guard, previous in candidates:
            limit = max(1, min(HISTORY_PREFIX_LIMIT, entry.size_bytes))
            value = dict(guard=guard, disposition=Disposition.PENDING, reason=Reason.BUDGET,
                         attempt=previous.get("attempt", 0) if previous else 0)
            if attempted < max_files and reserved + limit + 1 <= max_bytes:
                attempted += 1
                reserved += limit + 1
                sequence += 1
                kind, reason, diagnostic, consumed = _inspect(entry, row, limit)
                bytes_read += consumed
                value.update(disposition=kind, reason=reason, diagnostic=diagnostic, attempt=sequence)
            elif previous and previous["disposition"] == Disposition.PENDING and previous["reason"] != Reason.BUDGET:
                value = previous
            store_decision(connection, key, value)
            decisions[key] = value
        for key in absent:
            previous = decision(connection, key)
            store_decision(connection, key, dict(disposition=Disposition.PENDING, reason=Reason.UNAVAILABLE,
                diagnostic="captured_source_not_in_inventory", attempt=previous.get("attempt", 0) if previous else 0))
        connection.execute("insert or replace into schema_meta(key,value) values ('history-upgrade-sequence',?)", (str(sequence),))
        protected = set(protected_keys) | absent | {key for key, value in decisions.items() if value["disposition"] != Disposition.UNCHANGED}
        for entry in inventory:
            value = decisions.get(entry.file_key)
            if value is None:
                continue
            if value["disposition"] == Disposition.UNCHANGED:
                connection.execute("update files set error='' where file_key=? and error=?",
                                   (entry.file_key, "stale append checkpoint: "+PENDING_ERROR))
            else:
                reason = REBUILD_ERROR if value["disposition"] == Disposition.REBUILD else PENDING_ERROR
                record_file_stale(connection, [entry.session_dir], entry, reason)
        reserved = protected | {str(old[key]["session_id"]) for key in protected if key in old and old[key]["session_id"]}
        physical = {identity.rollout_id for key in protected
                    if key in old and (identity := rollout_identity(Path(old[key]["path"]))) is not None}
        for key in protected & old.keys():
            identity = rollout_identity(Path(old[key]["path"]))
            if identity is not None:
                reserved.add(identity.thread_id if identity.thread_id == identity.rollout_id
                             else PAGE_KEY_PREFIX+identity.rollout_id)
        blocked = _expand_protected(connection, inventory, reserved, physical)
        blocked.update(reserved)
        for row in connection.execute("select key from schema_meta where key like ?", (WAIT_PREFIX+"%",)).fetchall():
            key = str(row[0])[len(WAIT_PREFIX):]
            receipt = decision(connection, key, waiting=True)
            if receipt and receipt.get("blocked_by") in reserved:
                blocked.add(key)
        _release_dependencies(connection, blocked)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return UpgradeDiscovery(frozenset(blocked), bytes_read, frozenset(reserved), frozenset(blocked-protected))


def _signature(entry, row):
    facts = (str(entry.path), entry.size_bytes, entry.mtime_ns, entry.source_device, entry.source_inode,
             row["session_id"], row["checkpoint_session_id"], row["byte_offset"], row["next_record_index"],
             row["head_sha256"], row["boundary_sha256"])
    return hashlib.sha256(json.dumps(facts).encode()).hexdigest()


def _sequence(connection):
    row = connection.execute("select value from schema_meta where key='history-upgrade-sequence'").fetchone()
    try:
        return max(0, int(row[0])) if row else 0
    except (ValueError, TypeError):
        return 0


def _snapshot(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _inspect(entry, row, limit):
    consumed = 0
    try:
        with entry.path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            if _snapshot(before)[:4] != (entry.source_device, entry.source_inode, entry.size_bytes, entry.mtime_ns):
                return Disposition.PENDING, Reason.CHANGED, "source_changed", consumed
            raw = handle.read(limit + 1)
            consumed = len(raw)
            if _snapshot(before) != _snapshot(os.fstat(handle.fileno())) or _snapshot(before) != _snapshot(entry.path.stat()):
                return Disposition.PENDING, Reason.CHANGED, "source_changed", consumed
        read = read_session_metadata_stream(entry.path, BytesIO(raw), max_bytes=limit)
        metadata = read.metadata
        if metadata is None:
            return Disposition.PENDING, Reason.INVALID, read.diagnostic, consumed
        validate_page_metadata(metadata)
        if metadata.session_id != row["session_id"] or metadata.session_id != row["checkpoint_session_id"]:
            return Disposition.PENDING, Reason.INVALID, "captured_identity_mismatch", consumed
        physical_page = metadata.history_mode == "paginated" and source_identity(metadata).startswith(PAGE_KEY_PREFIX)
        if physical_page or metadata.history_base is not None or metadata.forked_from_ordinal_exclusive is not None:
            return Disposition.REBUILD, Reason.INHERITED, "", consumed
        return Disposition.UNCHANGED, Reason.NO_INHERITED_PREFIX, "", consumed
    except OSError:
        return Disposition.PENDING, Reason.UNAVAILABLE, "source_unavailable", consumed
    except PaginatedHistoryError as error:
        return Disposition.PENDING, Reason.INVALID, str(error), consumed


def _retired_capture(connection, source_key):
    if connection.execute("select 1 from sqlite_master where type='table' and name='ledger_generations'").fetchone() is None:
        return False
    row = connection.execute("""select count(*), sum(g.status!='superseded') from ledger_generations g
        join ledger_sources s using(source_id) where s.source_key=?""", (source_key,)).fetchone()
    return bool(row[0]) and not row[1]


def _expand_protected(connection, inventory, protected, physical):
    if not protected:
        return set()
    blocked = set()
    for entry in inventory:
        if entry.file_key in protected:
            blocked.add(entry.file_key)
            continue
        identity = rollout_identity(entry.path)
        if identity is not None:
            slot = identity.thread_id if identity.thread_id == identity.rollout_id else PAGE_KEY_PREFIX+identity.rollout_id
            if identity.rollout_id in physical or slot in protected:
                blocked.add(entry.file_key)
        row = connection.execute("select * from files where file_key=?", (entry.file_key,)).fetchone()
        if row is not None and cached_source_identity(connection, entry, row) in protected:
            blocked.add(entry.file_key)
    return blocked


def defer_upgrade_dependency(connection, entry, *, blocked_by=None):
    previous = decision(connection, entry.file_key, waiting=True)
    if blocked_by is None and previous:
        blocked_by = previous.get("blocked_by")
    store_decision(connection, entry.file_key,
        dict(disposition=Disposition.PENDING, reason=Reason.DEPENDENCY, blocked_by=blocked_by), waiting=True)
    row = connection.execute("select 1 from files where file_key=?", (entry.file_key,)).fetchone()
    if row is not None:
        record_file_stale(connection, [entry.session_dir], entry, "accounting_upgrade_dependency_pending")


def _release_dependencies(connection, blocked):
    rows = connection.execute("select key from schema_meta where key like ?", (WAIT_PREFIX+"%",)).fetchall()
    for row in rows:
        key = str(row[0])[len(WAIT_PREFIX):]
        if key in blocked:
            continue
        connection.execute("update files set error='' where file_key=? and error=?", (key, WAIT_ERROR))
        connection.execute("delete from schema_meta where key=?", (WAIT_PREFIX+key,))
