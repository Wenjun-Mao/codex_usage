"""Private, coherent, hash-bound SQLite snapshots before accounting repair."""
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _facts(connection):
    revision = connection.execute(
        "select value from ledger_meta where key='ledger_revision'").fetchone()
    if revision is None:
        raise ValueError("Snapshot source is not a revisioned usage ledger")
    return {
        "ledger_revision": int(revision[0]),
        "schema_version": int(connection.execute(
            "select value from ledger_meta where key='schema_version'").fetchone()[0]),
        "usage_events": connection.execute("select count(*) from ledger_usage_events").fetchone()[0],
        "sources": connection.execute("select count(*) from ledger_sources").fetchone()[0],
    }


def _check_database(connection):
    if connection.execute("pragma quick_check").fetchall() != [("ok",)]:
        raise ValueError("Repair snapshot failed SQLite quick_check")
    if connection.execute("pragma foreign_key_check").fetchone() is not None:
        raise ValueError("Repair snapshot has foreign-key violations")


def create_repair_snapshot(source: Path, destination: Path, *, progress=None):
    """Never overwrite a destination or open the source with write permission.

    The pinned read transaction includes committed WAL data, not a filesystem
    copy of whichever main-database pages happened to have been checkpointed.
    """
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if source == destination.resolve(strict=False):
        raise ValueError("Repair snapshot must be separate from its source")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5) as origin:
        origin.execute("pragma query_only=on")
        origin.execute("begin")
        facts = _facts(origin)
        destination.parent.mkdir(mode=0o700, parents=False, exist_ok=False)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        with sqlite3.connect(destination) as target:
            origin.backup(target, pages=256, progress=progress, sleep=.01)
            _check_database(target)
            if _facts(target) != facts:
                raise ValueError("Repair snapshot does not match pinned source facts")
        origin.rollback()
    os.chmod(destination, 0o600)
    manifest = {
        "format": "codex-usage-private-repair-snapshot-1",
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(source), "source_open_mode": "ro",
        "snapshot": str(destination), "size_bytes": destination.stat().st_size,
        "sha256": _digest(destination), **facts,
    }
    receipt = destination.parent / "snapshot.json"
    with receipt.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    os.chmod(receipt, 0o600)
    verify_repair_snapshot(receipt)
    return receipt


def verify_repair_snapshot(receipt: Path):
    manifest = json.loads(receipt.read_text(encoding="utf-8"))
    if manifest.get("format") != "codex-usage-private-repair-snapshot-1":
        raise ValueError("Unknown repair snapshot format")
    path = Path(manifest["snapshot"])
    if path.parent != receipt.absolute().parent:
        raise ValueError("Repair snapshot must remain beside its receipt")
    if path.stat().st_size != manifest["size_bytes"] or _digest(path) != manifest["sha256"]:
        raise ValueError("Repair snapshot hash/size mismatch")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        _check_database(connection)
        facts = _facts(connection)
        if facts != {key: manifest[key] for key in facts}:
            raise ValueError("Repair snapshot facts mismatch")
    return manifest


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    receipt = create_repair_snapshot(args.ledger, args.destination)
    manifest = verify_repair_snapshot(receipt)
    print(json.dumps({"receipt": str(receipt), "ledger_revision": manifest["ledger_revision"],
                      "sha256": manifest["sha256"], "source_open_mode": "ro"}))


if __name__ == "__main__":
    main()
