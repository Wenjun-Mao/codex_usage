from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from codex_usage.project_identity import normalize_project_key
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
)
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import SyncFileSnapshot


_TRANSIENT_ERRNOS = frozenset(
    value
    for name in ("EAGAIN", "EBUSY", "EINTR", "ESTALE", "ETIMEDOUT", "ETXTBSY")
    if (value := getattr(errno, name, None)) is not None
)
_TRANSIENT_WINERRORS = frozenset({32, 33, 54, 121, 170, 1237})


@dataclass(frozen=True)
class _PreparedSession:
    written: SyncFileSnapshot
    observed_source: SyncFileSnapshot


def _is_transient_filesystem_error(error: BaseException) -> bool:
    if not isinstance(error, OSError) or isinstance(error, FileNotFoundError):
        return False
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        return winerror in _TRANSIENT_WINERRORS
    return error.errno in _TRANSIENT_ERRNOS


def materialize_session_cwd(
    source: Path,
    target: Path,
    *,
    local_cwd: Path,
    project_identities: frozenset[str],
    expected_target: SyncFileSnapshot,
    expected_source: SyncFileSnapshot | None = None,
) -> SyncFileSnapshot:
    """Copy a session while rebinding only its session metadata cwd."""
    return _materialize_session_cwd(
        source,
        target,
        local_cwd=local_cwd,
        project_identities=project_identities,
        expected_target=expected_target,
        expected_source=expected_source,
    )


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _materialize_session_cwd(
    source: Path,
    target: Path,
    *,
    local_cwd: Path,
    project_identities: frozenset[str],
    expected_target: SyncFileSnapshot,
    expected_source: SyncFileSnapshot | None,
) -> SyncFileSnapshot:
    desired_cwd = str(local_cwd)
    if not project_identities:
        raise ValueError("Project identities are required for cwd materialization")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            delete=False,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as temporary:
            temporary_path = Path(temporary.name)
            prepared = _write_materialized_session(
                source,
                temporary,
                temporary_path,
                desired_cwd,
                project_identities,
            )
        _validate_expected_source(
            source,
            expected_source,
            prepared.observed_source,
        )
        _validate_expected_target(target, expected_target)
        temporary_path.replace(target)
        actual = snapshot_file(target)
        if actual != SyncFileSnapshot(
            path=target,
            exists=True,
            sha256=prepared.written.sha256,
            size_bytes=prepared.written.size_bytes,
        ):
            raise ConcurrentLocalChangeError(
                "Local task changed after cwd materialization"
            )
        return actual
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_materialized_session(
    source: Path,
    target: BinaryIO,
    temporary_path: Path,
    desired_cwd: str,
    project_identities: frozenset[str],
) -> _PreparedSession:
    source_digest = hashlib.sha256()
    written_digest = hashlib.sha256()
    source_size_bytes = 0
    written_size_bytes = 0
    matched_metadata = 0
    identity_cache: dict[tuple[str, str], str] = {}
    with source.open("rb") as source_file:
        while line := source_file.readline():
            source_digest.update(line)
            source_size_bytes += len(line)
            output = line
            if b"session_meta" in line:
                parsed = _json_object(line)
                if parsed is not None and parsed.get("type") == "session_meta":
                    payload = parsed.get("payload")
                    if not isinstance(payload, dict):
                        raise ValueError("Session metadata payload must be an object")
                    identity = _metadata_project_identity(payload, identity_cache)
                    if identity in project_identities:
                        matched_metadata += 1
                        if str(payload.get("cwd") or "") != desired_cwd:
                            payload["cwd"] = desired_cwd
                            output = _encode_json_line(parsed, line)
            target.write(output)
            written_digest.update(output)
            written_size_bytes += len(output)
    if not matched_metadata:
        raise ValueError(
            f"No session metadata matched the selected project in {source}"
        )
    target.flush()
    os.fsync(target.fileno())
    return _PreparedSession(
        written=SyncFileSnapshot(
            temporary_path,
            True,
            written_digest.hexdigest(),
            written_size_bytes,
        ),
        observed_source=SyncFileSnapshot(
            source,
            True,
            source_digest.hexdigest(),
            source_size_bytes,
        ),
    )


def _metadata_project_identity(
    payload: dict[str, object],
    cache: dict[tuple[str, str], str],
) -> str:
    git = payload.get("git")
    repository_url = (
        str(git.get("repository_url") or "") if isinstance(git, dict) else ""
    )
    cwd = str(payload.get("cwd") or "")
    cache_key = (repository_url, cwd)
    if cache_key not in cache:
        cache[cache_key] = normalize_project_key(repository_url or cwd)
    return cache[cache_key]


def _json_object(line: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _encode_json_line(value: dict[str, object], original: bytes) -> bytes:
    newline = (
        b"\r\n"
        if original.endswith(b"\r\n")
        else b"\n"
        if original.endswith(b"\n")
        else b""
    )
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + newline
    )


def _validate_expected_source(
    source: Path,
    expected_source: SyncFileSnapshot | None,
    observed_source: SyncFileSnapshot,
) -> None:
    if expected_source is not None and (
        observed_source != expected_source or snapshot_file(source) != expected_source
    ):
        raise ConcurrentRemoteChangeError(
            "Remote task changed during cwd materialization"
        )


def _validate_expected_target(target: Path, expected: SyncFileSnapshot) -> None:
    if snapshot_file(target) != expected:
        raise ConcurrentLocalChangeError(
            "Local task changed before cwd materialization"
        )
