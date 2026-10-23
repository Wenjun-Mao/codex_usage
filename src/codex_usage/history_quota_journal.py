"""Bounded independent quota mutation certificates for structural prefix reuse."""
TABLE = "dashboard_preparation_quota_changes"
TABLE_SQL = f"CREATE TABLE {TABLE} (generation integer primary key, start real not null)"
LIMIT = 4096


def _start(row):
    # Blobs can contain mixed-offset timestamps outside their lexical endpoints.
    return (f"case when {row}.timestamps_blob is not null then -1e300 else min("
            f"coalesce(cast(strftime('%s', {row}.timestamp) as real)-1, -1e300), "
            f"coalesce(cast(strftime('%s', {row}.last_timestamp) as real)-1, -1e300)) end")


def mutation_sql(table, event, state_table):
    if table not in ("quota_observations", "quota_provenance"):
        return ""
    rows = ("old", "new") if event == "update" else ("old",) if event == "delete" else ("new",)
    if table == "quota_observations":
        expressions = [_start(row) for row in rows]
    else:
        expressions = [f"coalesce((select {_start('o')} from quota_observations o "
                       f"where observation_key={row}.observation_key), -1e300)" for row in rows]
    start = expressions[0] if len(expressions) == 1 else "min(" + ",".join(expressions) + ")"
    return (f"insert into {TABLE} select quota_generation, {start} from {state_table}; "
            f"delete from {TABLE} where generation <= (select quota_generation-{LIMIT} from {state_table});")


def prefix_unchanged(connection, previous, current, end):
    """Gaps, rollback/repair epochs and backwards edits all fail closed."""
    if (not isinstance(previous, (tuple, list)) or len(previous) != 3 or current is None
            or previous[0] != current[0] or type(previous[2]) is not int
            or not 0 <= current[2] - previous[2] <= LIMIT):
        return False
    if previous[2] == current[2]:
        return True
    row = connection.execute(f"select count(*), min(start) from {TABLE} "
        "where generation > ? and generation <= ?", (previous[2], current[2])).fetchone()
    return row[0] == current[2] - previous[2] and row[1] is not None and row[1] > end
