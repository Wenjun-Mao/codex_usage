from __future__ import annotations

import hashlib
import json
import re
import tarfile
from collections import deque
from pathlib import Path, PurePosixPath

import zstandard
from pydantic import ValidationError

from codex_usage.task_backup.filesystem import open_binary_read, stat_path
from codex_usage.task_backup.models import (
    MAX_SESSION_INDEX_BYTES,
    MANIFEST_MEMBER,
    SESSION_INDEX_MEMBER,
    BackupManifest,
    VerificationResult,
)
from codex_usage.task_backup.progress import (
    ProgressCallback,
    ThrottledProgress,
    ignore_progress,
)


_PAYLOAD_MEMBER = re.compile(r"^payload/[0-9]{6}\.jsonl$")
_READ_CHUNK_SIZE = 1024 * 1024
_COMPRESSED_READ_SIZE = 64 * 1024
_RECENT_DECOMPRESSED_BYTES = 1024 * 1024
_PAX_SIZE_THRESHOLD = 8**11


class BackupVerificationError(RuntimeError):
    pass


def verify_task_backup(
    archive_path: Path,
    *,
    progress: ProgressCallback = ignore_progress,
) -> VerificationResult:
    path = archive_path.expanduser().absolute()
    try:
        archive_bytes = stat_path(path).st_size
    except OSError as error:
        raise BackupVerificationError(f"Backup archive is unavailable: {path}") from error
    verifier_progress = ThrottledProgress(
        progress,
        phase="verifying",
        total_bytes=archive_bytes,
        file_count=0,
    )
    digester = hashlib.sha256()
    observed: dict[str, tuple[int, str, bytes | None]] = {}
    manifest: BackupManifest | None = None
    manifest_seen = False
    final_member_end: int | None = None
    try:
        with open_binary_read(path) as raw_input:
            uncompressed = _SingleFrameZstdReader(
                raw_input,
                digester,
                verifier_progress,
            )
            with tarfile.open(
                fileobj=uncompressed,
                mode="r|",
                bufsize=_COMPRESSED_READ_SIZE,
            ) as archive:
                for member in archive:
                    if manifest_seen:
                        raise BackupVerificationError(
                            "Archive contains data after manifest.json"
                        )
                    _validate_tar_member(member)
                    if member.name in observed:
                        raise BackupVerificationError(
                            f"Archive contains duplicate member: {member.name}"
                        )
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise BackupVerificationError(
                            f"Archive member could not be read: {member.name}"
                        )
                    capture = member.name in {MANIFEST_MEMBER, SESSION_INDEX_MEMBER}
                    size, digest, contents = _read_member(
                        handle,
                        expected_size=member.size,
                        capture=capture,
                    )
                    observed[member.name] = (size, digest, contents)
                    if member.name == MANIFEST_MEMBER:
                        manifest_seen = True
                        manifest = _parse_manifest(contents or b"")
                        final_member_end = _tar_block_end(
                            member.offset_data + member.size
                        )
                        uncompressed.mark_tar_end(final_member_end)
            if final_member_end is None:
                raise BackupVerificationError(
                    "Archive does not contain a final manifest.json"
                )
            uncompressed.validate_tar_termination()
    except BackupVerificationError:
        raise
    except (OSError, tarfile.TarError, zstandard.ZstdError) as error:
        raise BackupVerificationError(f"Backup archive is damaged: {error}") from error
    verifier_progress.finish()
    if manifest is None:
        raise BackupVerificationError("Archive does not contain a final manifest.json")
    _validate_manifest(manifest, observed)
    return VerificationResult(
        archive_path=path,
        manifest=manifest,
        archive_bytes=archive_bytes,
        archive_sha256=digester.hexdigest(),
    )


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    if not member.isreg():
        raise BackupVerificationError(
            f"Archive contains a non-regular member: {member.name}"
        )
    if member.name not in {MANIFEST_MEMBER, SESSION_INDEX_MEMBER} and not _PAYLOAD_MEMBER.fullmatch(
        member.name
    ):
        raise BackupVerificationError(f"Archive contains an unsupported member: {member.name}")
    if member.size < 0:
        raise BackupVerificationError(f"Archive member has an invalid size: {member.name}")
    if member.name in {MANIFEST_MEMBER, SESSION_INDEX_MEMBER} and member.size > MAX_SESSION_INDEX_BYTES:
        raise BackupVerificationError(f"Archive metadata member is too large: {member.name}")
    if (
        member.mode != 0o600
        or member.uid != 0
        or member.gid != 0
        or member.mtime != 0
        or member.uname
        or member.gname
    ):
        raise BackupVerificationError(f"Archive member metadata is not canonical: {member.name}")
    expected_pax = (
        {"size": str(member.size)} if member.size >= _PAX_SIZE_THRESHOLD else {}
    )
    if member.pax_headers != expected_pax:
        raise BackupVerificationError(
            f"Archive member PAX metadata is not canonical: {member.name}"
        )


def _read_member(
    handle: object,
    *,
    expected_size: int,
    capture: bool,
) -> tuple[int, str, bytes | None]:
    digest = hashlib.sha256()
    chunks: list[bytes] | None = [] if capture else None
    size = 0
    while True:
        chunk = handle.read(_READ_CHUNK_SIZE)  # type: ignore[attr-defined]
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
        if chunks is not None:
            chunks.append(chunk)
    if size != expected_size:
        raise BackupVerificationError("Archive member ended before its declared size")
    return size, digest.hexdigest(), b"".join(chunks) if chunks is not None else None


def _parse_manifest(contents: bytes) -> BackupManifest:
    try:
        value = json.loads(contents)
        return BackupManifest.model_validate(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise BackupVerificationError(f"Backup manifest is invalid: {error}") from error


def _validate_manifest(
    manifest: BackupManifest,
    observed: dict[str, tuple[int, str, bytes | None]],
) -> None:
    if manifest.compression.preset == "maximum" and manifest.compression.level != 19:
        raise BackupVerificationError("Maximum compression level is not canonical")
    if manifest.compression.preset == "balanced" and manifest.compression.level != 9:
        raise BackupVerificationError("Balanced compression level is not canonical")
    expected_members = {
        *(entry.member for entry in manifest.files),
        manifest.session_index.member,
        MANIFEST_MEMBER,
    }
    if set(observed) != expected_members:
        missing = sorted(expected_members - set(observed))
        extra = sorted(set(observed) - expected_members)
        raise BackupVerificationError(
            f"Archive members do not match manifest; missing={missing}, extra={extra}"
        )
    if len(manifest.files) != manifest.physical_file_count:
        raise BackupVerificationError("Manifest physical file count is inconsistent")
    if len({entry.member for entry in manifest.files}) != len(manifest.files):
        raise BackupVerificationError("Manifest contains duplicate payload members")
    expected_names = [f"payload/{index:06d}.jsonl" for index in range(1, len(manifest.files) + 1)]
    if [entry.member for entry in manifest.files] != expected_names:
        raise BackupVerificationError("Manifest payload members are not in canonical order")
    for entry in manifest.files:
        _validate_relative_source(entry.original_relative_path, entry.storage_state)
        size, digest, _ = observed[entry.member]
        if (size, digest) != (entry.size_bytes, entry.sha256):
            raise BackupVerificationError(
                f"Payload does not match manifest: {entry.member}"
            )
    if sum(entry.size_bytes for entry in manifest.files) != manifest.source_bytes:
        raise BackupVerificationError("Manifest source byte total is inconsistent")
    index_size, index_digest, index_contents = observed[SESSION_INDEX_MEMBER]
    if (index_size, index_digest) != (
        manifest.session_index.size_bytes,
        manifest.session_index.sha256,
    ):
        raise BackupVerificationError("Session index metadata does not match manifest")
    _validate_session_index(
        index_contents or b"",
        manifest.session_index.entry_count,
        {entry.task_id for entry in manifest.files},
    )
    _validate_task_tree(manifest)


def _validate_relative_source(relative_path: str, storage_state: str) -> None:
    if "\\" in relative_path:
        raise BackupVerificationError("Manifest source path must use POSIX separators")
    value = PurePosixPath(relative_path)
    if value.is_absolute() or ".." in value.parts or value.suffix != ".jsonl":
        raise BackupVerificationError(f"Manifest contains unsafe source path: {relative_path}")
    expected_root = "sessions" if storage_state == "active" else "archived_sessions"
    if not value.parts or value.parts[0] != expected_root:
        raise BackupVerificationError(
            f"Manifest storage state does not match source path: {relative_path}"
        )


def _validate_session_index(contents: bytes, expected_count: int, task_ids: set[str]) -> None:
    count = 0
    for raw_line in contents.splitlines():
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupVerificationError("Archived session index contains invalid JSON") from error
        if not isinstance(value, dict) or str(value.get("id") or "") not in task_ids:
            raise BackupVerificationError("Archived session index references another task")
        count += 1
    if count != expected_count:
        raise BackupVerificationError("Archived session index entry count is inconsistent")


def _validate_task_tree(manifest: BackupManifest) -> None:
    tree = manifest.task_tree
    if tree.tree_id != tree.root_task_id:
        raise BackupVerificationError("Manifest task tree identity is inconsistent")
    if tree.recovery_ready and tree.diagnostics:
        raise BackupVerificationError("Recovery-ready backup cannot contain diagnostics")
    if not tree.recovery_ready and not tree.diagnostics:
        raise BackupVerificationError("Salvage backup must explain why it is not recovery-ready")
    if not tree.recovery_ready:
        return
    relationships: dict[str, tuple[str, str]] = {}
    for entry in manifest.files:
        relationship = (entry.usage_role, entry.parent_task_id)
        existing = relationships.setdefault(entry.task_id, relationship)
        if existing != relationship:
            raise BackupVerificationError(
                "Recovery-ready backup has inconsistent duplicate task metadata"
            )
    if relationships.get(tree.root_task_id) != ("root", ""):
        raise BackupVerificationError("Recovery-ready backup does not contain its root task")
    for task_id, (usage_role, parent_task_id) in relationships.items():
        if task_id != tree.root_task_id and (
            usage_role != "subagent" or not parent_task_id
        ):
            raise BackupVerificationError(
                "Recovery-ready backup contains an unrelated root task"
            )
        seen: set[str] = set()
        current = task_id
        while current != tree.root_task_id:
            if current in seen:
                raise BackupVerificationError("Recovery-ready backup has a task cycle")
            seen.add(current)
            relationship = relationships.get(current)
            if relationship is None or relationship[0] != "subagent":
                raise BackupVerificationError(
                    "Recovery-ready backup has a missing task parent"
                )
            current = relationship[1]


def _tar_block_end(offset: int) -> int:
    return ((offset + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE


class _SingleFrameZstdReader:
    """Bounded streaming reader that proves one exact zstd frame and TAR suffix."""

    def __init__(self, handle: object, digest: object, progress: ThrottledProgress) -> None:
        self._handle = handle
        self._digest = digest
        self._progress = progress
        self._decoder = zstandard.ZstdDecompressor().decompressobj()
        self._output: deque[bytes] = deque()
        self._output_offset = 0
        self._output_size = 0
        self._frame_done = False
        self._position = 0
        self._recent: deque[tuple[int, bytes]] = deque()
        self._recent_size = 0
        self._tar_end: int | None = None
        self._suffix_size = 0
        self._suffix_nonzero = False

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        if size < 0:
            chunks: list[bytes] = []
            while chunk := self.read(_READ_CHUNK_SIZE):
                chunks.append(chunk)
            return b"".join(chunks)
        while self._output_size < size and not self._frame_done:
            self._fill()
        chunk = self._take(min(size, self._output_size))
        self._record(chunk)
        return chunk

    def readable(self) -> bool:
        return True

    def mark_tar_end(self, offset: int) -> None:
        if self._tar_end is not None:
            raise BackupVerificationError("Archive contains more than one final manifest")
        if offset > self._position:
            raise BackupVerificationError("Archive manifest data was not fully consumed")
        earliest = self._recent[0][0] if self._recent else self._position
        if offset < earliest:
            raise BackupVerificationError(
                "Archive reader could not prove the final TAR boundary"
            )
        self._tar_end = offset
        for start, chunk in self._recent:
            relative = max(0, offset - start)
            if relative >= len(chunk):
                continue
            suffix = chunk[relative:]
            self._suffix_size += len(suffix)
            self._suffix_nonzero = self._suffix_nonzero or any(suffix)

    def validate_tar_termination(self) -> None:
        if self._tar_end is None:
            raise BackupVerificationError("Archive has no final TAR boundary")
        while self.read(_READ_CHUNK_SIZE):
            pass
        minimum_end = self._tar_end + (2 * tarfile.BLOCKSIZE)
        expected_size = (
            (minimum_end + tarfile.RECORDSIZE - 1) // tarfile.RECORDSIZE
        ) * tarfile.RECORDSIZE
        if self._suffix_nonzero:
            raise BackupVerificationError("Archive contains non-zero data after manifest.json")
        if self._position != expected_size or self._suffix_size != expected_size - self._tar_end:
            raise BackupVerificationError("Archive TAR termination is not canonical")

    def _fill(self) -> None:
        raw_chunk = self._handle.read(_COMPRESSED_READ_SIZE)  # type: ignore[attr-defined]
        if not raw_chunk:
            if not self._decoder.eof:
                raise BackupVerificationError("Backup zstd frame ended unexpectedly")
            self._frame_done = True
            return
        self._digest.update(raw_chunk)  # type: ignore[attr-defined]
        self._progress.advance(len(raw_chunk))
        output = self._decoder.decompress(raw_chunk)
        if output:
            self._output.append(output)
            self._output_size += len(output)
        if self._decoder.eof:
            flushed = self._decoder.flush()
            if flushed:
                self._output.append(flushed)
                self._output_size += len(flushed)
            if self._decoder.unused_data or self._handle.read(1):  # type: ignore[attr-defined]
                raise BackupVerificationError(
                    "Archive contains trailing compressed data or another zstd frame"
                )
            self._frame_done = True

    def _take(self, size: int) -> bytes:
        if size <= 0:
            return b""
        remaining = size
        parts: list[bytes] = []
        while remaining:
            current = self._output[0]
            available = len(current) - self._output_offset
            take = min(remaining, available)
            parts.append(current[self._output_offset : self._output_offset + take])
            self._output_offset += take
            self._output_size -= take
            remaining -= take
            if self._output_offset == len(current):
                self._output.popleft()
                self._output_offset = 0
        return b"".join(parts)

    def _record(self, chunk: bytes) -> None:
        if not chunk:
            return
        start = self._position
        self._position += len(chunk)
        if self._tar_end is not None:
            suffix_start = max(0, self._tar_end - start)
            if suffix_start < len(chunk):
                suffix = chunk[suffix_start:]
                self._suffix_size += len(suffix)
                self._suffix_nonzero = self._suffix_nonzero or any(suffix)
            return
        self._recent.append((start, chunk))
        self._recent_size += len(chunk)
        while self._recent_size > _RECENT_DECOMPRESSED_BYTES and len(self._recent) > 1:
            _, removed = self._recent.popleft()
            self._recent_size -= len(removed)
