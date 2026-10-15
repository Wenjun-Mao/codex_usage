"""Connection-scoped DML authority for the versioned usage ledger."""

LEDGER_SCHEMA_VERSION = 7
WRITER_EPOCH = 1
WRITER_FUNCTION = "codex_usage_writer_epoch"
WRITER_EPOCH_KEY = "accounting_writer_epoch"
TRIGGER_PREFIX = "codex_writer_"
PROTECTED_TABLES = frozenset("""allowance_event_costs allowance_report_cache capture_runs credit_observations
    dirty_transition_tasks files image_operations ledger_contexts ledger_generations ledger_image_events
    ledger_meta ledger_models ledger_projects ledger_sources ledger_speed_facts ledger_speed_identities
    ledger_tasks ledger_transitions ledger_usage_events migration_audit parser_checkpoints project_transitions
    quota_cache quota_observations quota_provenance quota_reads quota_recovery rendered_reports schema_meta
    session_metadata speed_cache_dirty speed_cache_facts speed_cache_tools speed_cache_uncertain_tools
    speed_html_cache speed_recovery speed_report_cache storage_content_diagnostics storage_files
    transition_candidates usage_records""".split())


class LedgerCompatibilityError(ValueError):
    """An incompatible ledger must not be opened as a disposable cache."""


def admit_ledger_privacy_paths(path):
    path = path.expanduser().absolute()
    if (path.parent.is_symlink() or path.is_symlink()
            or any(path.with_name(path.name+suffix).is_symlink() for suffix in ("-wal", "-shm", "-journal"))):
        raise LedgerCompatibilityError("usage ledger requires canonical nonsymlink database and sidecar paths")
    return path.parent.resolve() / path.name


def ledger_schema_version(connection):
    if connection.execute("select 1 from sqlite_master where type='table' and name='ledger_meta'").fetchone() is None:
        if connection.execute("""select 1 from sqlite_master where type='table'
            and name in ('ledger_sources','ledger_generations','ledger_usage_events') limit 1""").fetchone():
            raise LedgerCompatibilityError("usage ledger metadata is missing; refusing new-ledger initialization")
        return 0
    row = connection.execute("select value from ledger_meta where key='schema_version'").fetchone()
    try:
        value = int(row[0])
        if value < 1 or str(value) != row[0]:
            raise ValueError
        return value
    except (ValueError, TypeError, IndexError) as error:
        raise LedgerCompatibilityError("invalid usage ledger schema version") from error


def assert_supported_ledger_schema(connection):
    version = ledger_schema_version(connection)
    if version > LEDGER_SCHEMA_VERSION:
        raise LedgerCompatibilityError(f"ledger schema {version} is newer than supported schema {LEDGER_SCHEMA_VERSION}")


def assert_legacy_writer_metadata(connection):
    epoch = connection.execute("select 1 from ledger_meta where key=?", (WRITER_EPOCH_KEY,)).fetchone()
    guards = connection.execute("select 1 from sqlite_master where type='trigger' and name like ?",
                                (TRIGGER_PREFIX+"%",)).fetchone()
    if epoch is not None or guards is not None:
        raise LedgerCompatibilityError("legacy ledger has inconsistent writer-contract metadata")


def authorize_writer_connection(connection):
    connection.create_function(WRITER_FUNCTION, 0, lambda: WRITER_EPOCH, deterministic=True)


def _trigger(table, operation):
    name = TRIGGER_PREFIX+table+"_"+operation.lower()
    sql = (f'CREATE TRIGGER "{name}" BEFORE {operation} ON "{table}" '
           f"WHEN {WRITER_FUNCTION}() IS NOT {WRITER_EPOCH} "
           "BEGIN SELECT RAISE(ABORT, 'unsupported Codex Usage ledger writer epoch'); END")
    return name, sql


def install_writer_contract(connection):
    if not connection.in_transaction:
        raise RuntimeError("writer fencing requires the schema migration transaction")
    connection.execute("insert into ledger_meta(key,value) values (?,?)", (WRITER_EPOCH_KEY, str(WRITER_EPOCH)))
    for table in sorted(PROTECTED_TABLES):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            _, sql = _trigger(table, operation)
            connection.execute(sql)


def validate_writer_contract(connection):
    version = ledger_schema_version(connection)
    if version > LEDGER_SCHEMA_VERSION:
        raise LedgerCompatibilityError(f"ledger schema {version} is newer than supported schema {LEDGER_SCHEMA_VERSION}")
    if version != LEDGER_SCHEMA_VERSION:
        raise LedgerCompatibilityError("usage ledger requires a quiescent writer-contract upgrade")
    row = connection.execute("select value from ledger_meta where key=?", (WRITER_EPOCH_KEY,)).fetchone()
    if row is None or row[0] != str(WRITER_EPOCH):
        raise LedgerCompatibilityError("unsupported usage ledger writer epoch")
    actual = dict(connection.execute("select name,sql from sqlite_master where type='trigger' and name like ?",
                                     (TRIGGER_PREFIX+"%",)))
    expected = dict(_trigger(table, operation) for table in PROTECTED_TABLES for operation in ("INSERT", "UPDATE", "DELETE"))
    if actual != expected:
        raise LedgerCompatibilityError("usage ledger writer guards are missing or changed")


def authorize_cache_connection(connection):
    authorize_writer_connection(connection)
    if ledger_schema_version(connection):
        validate_writer_contract(connection)


def assert_disposable_cache_reset(connection):
    if ledger_schema_version(connection):
        raise LedgerCompatibilityError("ledger-backed parser schema mismatch; refusing disposable cache reset")
