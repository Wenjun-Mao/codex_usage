"""Invalidate captured descendants, without opening raw history or dropping facts."""
from collections import defaultdict, deque
import json
from pathlib import Path

from codex_usage.session_history_models import HistoryBoundary
from codex_usage.session_rollout_identity import rollout_identity

EPOCH_PREFIX = "history-invalidation:"
PENDING_PREFIX = "history-invalidation-pending:"
ERROR = "stale append checkpoint: history_dependency_changed"
INVALID_ERROR = "stale append checkpoint: history_dependencies_invalid"


def invalidation_epoch(connection, source_key):
    row = connection.execute("select value from schema_meta where key=?", (EPOCH_PREFIX+source_key,)).fetchone()
    if row is None:
        return 0
    return parse_invalidation_epoch(row[0])


def parse_invalidation_epoch(raw):
    try:
        value = int(raw)
        if value < 0 or str(value) != raw:
            raise ValueError
        return value
    except (ValueError, TypeError) as error:
        raise RuntimeError("invalid history invalidation epoch") from error


def pending_invalidation(connection, source_key):
    row = connection.execute("select value from schema_meta where key=?", (PENDING_PREFIX+source_key,)).fetchone()
    if row is None:
        return False
    epoch = parse_invalidation_epoch(row[0])
    if not epoch or epoch != invalidation_epoch(connection, source_key):
        raise RuntimeError("inconsistent pending history invalidation")
    return True


def rekey_invalidation(connection, source_key, replacement_key):
    if source_key == replacement_key:
        return
    for prefix in (EPOCH_PREFIX, PENDING_PREFIX):
        source = connection.execute("select value from schema_meta where key=?", (prefix+source_key,)).fetchone()
        target = connection.execute("select value from schema_meta where key=?", (prefix+replacement_key,)).fetchone()
        if target is not None and (source is None or target[0] != source[0]):
            raise RuntimeError("history invalidation identity target is occupied")
        if source is not None:
            connection.execute("insert or replace into schema_meta(key,value) values (?,?)", (prefix+replacement_key, source[0]))
            connection.execute("delete from schema_meta where key=?", (prefix+source_key,))


def complete_invalidation(connection, source_key):
    if pending_invalidation(connection, source_key):
        connection.execute("delete from schema_meta where key=?", (PENDING_PREFIX+source_key,))


def pending_repair_guards(connection):
    from codex_usage.session_history import PAGE_KEY_PREFIX
    rows = connection.execute("""select f.file_key,f.path from files f
        join schema_meta m on m.key=?||f.file_key""", (PENDING_PREFIX,)).fetchall()
    protected = set()
    for row in rows:
        pending_invalidation(connection, row["file_key"])
        protected.add(row["file_key"])
        identity = rollout_identity(Path(row["path"]))
        if identity is not None:
            protected.add(identity.thread_id if identity.thread_id == identity.rollout_id
                          else PAGE_KEY_PREFIX+identity.rollout_id)
    return frozenset(protected)


def pending_report_row(connection, row, newly_invalidated):
    key = row["file_key"]
    if row["pending_history_invalidation"] is None and key not in newly_invalidated:
        return row
    if not pending_invalidation(connection, key):
        return row
    error = (connection.execute("select error from files where file_key=?", (key,)).fetchone()[0]
             if key in newly_invalidated else row["error"])
    if not error:
        error = ERROR
        connection.execute("update files set error=? where file_key=?", (error, key))
    return dict(row, error=error)


def _references(row):
    valid, invalid = [], False
    for raw, container in ((row["dependencies"], True), (row["direct_reference"], False)):
        if raw is None:
            continue
        try:
            values = json.loads(raw)
            if container and not isinstance(values, list):
                raise ValueError
        except (ValueError, TypeError):
            invalid = True
            continue
        for value in values if container else [values]:
            try:
                boundary = HistoryBoundary.from_mapping(value)
                if boundary is None:
                    raise ValueError
                valid.append(boundary)
            except (ValueError, TypeError):
                invalid = True
    return valid, invalid


def invalidate_dependents(connection, paths, *, exclude=()):
    if not connection.in_transaction:
        raise RuntimeError("history invalidation requires the accounting transaction")
    physical = {identity.rollout_id for path in paths if (identity := rollout_identity(Path(path))) is not None}
    if not physical:
        return set()
    state = "(case when json_valid(p.state_json) then p.state_json else '{}' end)"
    rows = connection.execute(f"""select f.file_key,f.path,
        json_extract({state},'$.history_dependencies') dependencies,
        json_extract({state},'$.root_metadata.history_base') direct_reference
        from files f join parser_checkpoints p using(file_key)""").fetchall()
    edges = defaultdict(set)
    physical_by_key = {}
    quarantined = set()
    for row in rows:
        key = str(row["file_key"])
        identity = rollout_identity(Path(row["path"]))
        if identity is not None:
            physical_by_key[key] = identity.rollout_id
        references, invalid = _references(row)
        if invalid:
            quarantined.add(key)
        for boundary in references:
            edges[boundary.rollout_id.lower()].add(key)
    affected = {key for key in quarantined - set(exclude) if not pending_invalidation(connection, key)}
    physical.update(physical_by_key[key] for key in affected if key in physical_by_key)
    pending, visited = deque(physical), set()
    while pending:
        parent = pending.popleft()
        if parent in visited:
            continue
        visited.add(parent)
        for key in edges[parent] - set(exclude) - affected:
            affected.add(key)
            if key in physical_by_key:
                pending.append(physical_by_key[key])
    for key in sorted(affected):
        epoch = invalidation_epoch(connection, key) + 1
        connection.execute("insert or replace into schema_meta(key,value) values (?,?)", (EPOCH_PREFIX+key, str(epoch)))
        connection.execute("insert or replace into schema_meta(key,value) values (?,?)", (PENDING_PREFIX+key, str(epoch)))
        connection.execute("""update files set error=case
            when error='' or error like 'stale append checkpoint:%' then ? else error end
            where file_key=?""", (INVALID_ERROR if key in quarantined else ERROR, key))
        connection.execute("""update ledger_sources set is_stale=1,
            stale_reason=(select error from files where file_key=?),
            error=(select error from files where file_key=?) where source_key=?""", (key, key, key))
    return affected
