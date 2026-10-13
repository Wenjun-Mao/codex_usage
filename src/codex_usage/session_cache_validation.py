"""Additive indexes for repeated parser-cache integrity checks."""


def ensure_role_validation_indexes(connection):
    # These indexes contain only corrupt rows. Valid ledgers pay no history scan
    # on each writer open; the existing validation predicates still run.
    for table in ("usage_records", "storage_files"):
        connection.execute(f"""create index if not exists {table}_invalid_role_idx
            on {table}(usage_role)
            where coalesce(usage_role, '') not in ('root', 'subagent')""")
