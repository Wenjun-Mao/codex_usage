from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LegacyCacheChangedError(RuntimeError):
    """The legacy cache changed after discovery or during a migration read."""


def legacy_cache_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for label, candidate in (
        (b"main", path),
        (b"wal", path.with_name(path.name + "-wal")),
    ):
        digest.update(label)
        if not candidate.is_file():
            digest.update(b"\0missing")
            continue
        size = candidate.stat().st_size
        digest.update(b"\0present\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def open_legacy_cache(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma busy_timeout = 5000")
    return connection


@contextmanager
def verified_legacy_cache(
    path: Path,
    expected_digest: str,
) -> Iterator[sqlite3.Connection]:
    before = legacy_cache_digest(path)
    if before != expected_digest:
        raise LegacyCacheChangedError(
            f"legacy cache changed after discovery: {path}"
        )
    connection = open_legacy_cache(path)
    try:
        yield connection
    finally:
        connection.close()
    after = legacy_cache_digest(path)
    if after != before:
        raise LegacyCacheChangedError(
            f"legacy cache changed while it was being read: {path}"
        )


def is_schema_eight(path: Path) -> bool:
    try:
        with open_legacy_cache(path) as connection:
            row = connection.execute(
                "select value from schema_meta where key = 'schema_version'"
            ).fetchone()
            return row is not None and str(row["value"]) == "8"
    except sqlite3.Error:
        return False
