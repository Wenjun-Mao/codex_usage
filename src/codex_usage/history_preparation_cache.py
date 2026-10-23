"""Bounded disposable pure-preparation results, published with the report snapshot."""
import hashlib
import json
import sqlite3

TABLE = "history_preparation_cache"
TABLE_SQL = (f"CREATE TABLE {TABLE} (slot text primary key, revision integer not null, "
             "payload text not null, checksum text not null, last_used integer not null)")
REVISION = 1
MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 8 * 1024 * 1024


def encode(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class HistoryPreparationCache:
    """No connections or object graphs survive the request; raw inputs stay authoritative.

    Callers verify complete content identities, not dirty spans or age. The
    publisher must check the snapshot's independent generation before finish.
    """

    def __init__(self, connection):
        from codex_usage.dashboard_preparation_tracking import token
        from codex_usage.ledger_schema import ReadOnlyLedgerConnection
        self.connection = connection
        self.dependency = (token(connection) if isinstance(connection, ReadOnlyLedgerConnection)
                           and connection.in_transaction else None)
        self.pending = {}
        self.used = set()
        self.pending_bytes = 0
        row = connection.execute("select sql from sqlite_master where type='table' and name=?", (TABLE,)).fetchone()
        self.available = row is not None and row[0] == TABLE_SQL

    def read(self, slot):
        if self.dependency is None:
            return None
        if slot in self.pending:
            payload, checksum = self.pending[slot]
        elif self.available:
            try:
                row = self.connection.execute(f"select payload, checksum from {TABLE} "
                    "where slot=? and revision=?", (slot, REVISION)).fetchone()
            except sqlite3.OperationalError:
                return None
            if row is None:
                return None
            payload, checksum = row
        else:
            return None
        if not isinstance(payload, str) or len(payload) > MAX_ENTRY_BYTES:
            return None
        if hashlib.sha256(payload.encode()).hexdigest() != checksum:
            return None
        try:
            result = json.loads(payload)
        except (ValueError, TypeError):
            return None
        self.used.add(slot)
        return result

    def stage(self, slot, value):
        if self.dependency is None:
            return
        payload = encode(value)
        size = len(payload.encode())
        previous = len(self.pending[slot][0].encode()) if slot in self.pending else 0
        if size > MAX_ENTRY_BYTES or self.pending_bytes - previous + size > MAX_BYTES:
            return
        self.pending_bytes += size - previous
        self.pending[slot] = (payload, hashlib.sha256(payload.encode()).hexdigest())
        self.used.add(slot)

    def prefix_unchanged(self, previous, end):
        from codex_usage.history_quota_journal import prefix_unchanged
        return prefix_unchanged(self.connection, previous, self.dependency, end)

    def finish(self, connection):
        from codex_usage.dashboard_preparation_tracking import token
        if not self.used or self.dependency is None or token(connection) != self.dependency:
            return
        row = connection.execute("select sql from sqlite_master where type='table' and name=?", (TABLE,)).fetchone()
        if row is None or row[0] != TABLE_SQL:
            connection.execute(f"drop table if exists {TABLE}")
            connection.execute(TABLE_SQL)
        generation = connection.execute(f"select coalesce(max(last_used),0)+1 from {TABLE}").fetchone()[0]
        connection.executemany(f"insert or replace into {TABLE} values (?,?,?,?,?)",
            [(slot, REVISION, payload, checksum, generation)
             for slot, (payload, checksum) in self.pending.items()])
        connection.executemany(f"update {TABLE} set last_used=? where slot=? and revision=?",
            [(generation, slot, REVISION) for slot in sorted(self.used)])
        connection.execute(f"delete from {TABLE} where revision != ?", (REVISION,))
        size = 0
        expired = []
        for slot, length in connection.execute(
                f"select slot, length(cast(payload as blob)) from {TABLE} order by last_used desc, slot"):
            size += length
            if size > MAX_BYTES:
                expired.append((slot,))
        connection.executemany(f"delete from {TABLE} where slot=?", expired)
