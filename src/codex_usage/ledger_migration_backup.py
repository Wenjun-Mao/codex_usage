"""Verified, nonoverwriting private backup under the maintenance locks."""
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4
from dataclasses import dataclass

from codex_usage.ledger_repair_snapshot import create_repair_snapshot, verify_repair_snapshot


@dataclass(frozen=True, slots=True)
class MigrationBackup:
    facts: tuple[int, int, int, int]
    data_version: int


def _facts(connection):
    schema = connection.execute("select value from ledger_meta where key='schema_version'").fetchone()
    revision = connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()
    return (int(schema[0]), int(revision[0]), connection.execute("select count(*) from ledger_usage_events").fetchone()[0],
            connection.execute("select count(*) from ledger_sources").fetchone()[0])


def assert_backup_current(connection, backup):
    if not connection.in_transaction or not isinstance(backup, MigrationBackup):
        raise RuntimeError("migration backup CAS requires the owned write transaction")
    if (_facts(connection) != backup.facts
            or connection.execute("pragma data_version").fetchone()[0] != backup.data_version):
        raise RuntimeError("usage ledger changed after its verified migration backup")


def backup_before_writer_upgrade(connection, path, version):
    data_version = connection.execute("pragma data_version").fetchone()[0]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = path.with_name(f"{path.name}.schema-{version}-backup-{stamp}-{uuid4().hex[:12]}") / "ledger.sqlite3"
    deadline = monotonic() + 300

    def progress(*_args):
        if monotonic() >= deadline:
            raise TimeoutError("ledger migration backup exceeded its bounded execution window")

    receipt = create_repair_snapshot(path, destination, progress=progress)
    manifest = verify_repair_snapshot(receipt)
    if manifest["schema_version"] != version:
        raise RuntimeError("usage ledger schema changed before its verified migration backup")
    return MigrationBackup((version, manifest["ledger_revision"], manifest["usage_events"], manifest["sources"]), data_version)
