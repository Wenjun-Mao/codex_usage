"""Queue exact, staged replacement only after the missing counter is provable."""
from pathlib import Path

from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_history import HISTORY_READ_BUDGET, HistorySource, resolve_baseline
from codex_usage.session_history_models import PaginatedHistoryError


def find_restored_openings(connection, inventory, *, budget):
    if budget < HISTORY_READ_BUDGET or connection.execute(
        "select 1 from sqlite_master where type='table' and name='ledger_sources'"
    ).fetchone() is None:
        return (), 0
    rows = connection.execute("""select f.file_key,f.path from files f
        join parser_checkpoints p using(file_key)
        where f.error='' and f.is_missing=0 and
            (case when json_valid(p.state_json)
                  then json_type(p.state_json,'$.history_gap_ordinal')='integer' end)
        order by f.file_key""").fetchall()
    if not rows:
        return (), 0

    current = {entry.path for entry in inventory}
    sources = tuple(HistorySource.from_inventory(entry) for entry in inventory)
    size_by_id = {}
    for source in sources:
        key = source.rollout_id_hint
        size_by_id[key] = max(size_by_id.get(key, 0), source.size_bytes)
    ready, used = [], 0
    for row in rows:
        if budget - used < HISTORY_READ_BUDGET:
            break
        path = Path(row["path"])
        if path not in current:
            continue
        checkpoint = load_parser_checkpoint(connection, row["file_key"], path)
        if checkpoint is None or checkpoint.state.history_gap_ordinal is None:
            continue
        metadata = checkpoint.state.root_metadata
        base = metadata.history_base
        if size_by_id.get(base.rollout_id.lower(), 0) < base.end_byte_offset:
            continue
        try:
            baseline = resolve_baseline(metadata, sources)
        except PaginatedHistoryError as error:
            used += error.bytes_read
        else:
            used += baseline.bytes_read
            ready.append(row["file_key"])
    return tuple(ready), used
