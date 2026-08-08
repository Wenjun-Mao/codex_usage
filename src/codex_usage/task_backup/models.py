from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


BACKUP_FORMAT = "codex-task-backup"
BACKUP_FORMAT_VERSION = 1
BACKUP_SUFFIX = ".codex-task-backup"
MANIFEST_MEMBER = "manifest.json"
SESSION_INDEX_MEMBER = "metadata/session-index.jsonl"
MAX_SESSION_INDEX_BYTES = 64 * 1024 * 1024
MAX_SESSION_INDEX_LINE_BYTES = 1024 * 1024
CompressionPreset = Literal["maximum", "balanced"]


class StrictBackupModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CompressionManifest(StrictBackupModel):
    algorithm: Literal["zstd"] = "zstd"
    preset: CompressionPreset
    level: int


class TaskTreeManifest(StrictBackupModel):
    tree_id: str = Field(min_length=1)
    root_task_id: str = Field(min_length=1)
    title: str
    project_key: str
    project_label: str
    project_aliases: list[str]
    recovery_ready: bool
    diagnostics: list[str]


class BackupFileManifest(StrictBackupModel):
    member: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    parent_task_id: str
    usage_role: Literal["root", "subagent"]
    storage_state: Literal["active", "archived"]
    original_relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SessionIndexManifest(StrictBackupModel):
    member: Literal["metadata/session-index.jsonl"] = SESSION_INDEX_MEMBER
    entry_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupManifest(StrictBackupModel):
    format: Literal["codex-task-backup"] = BACKUP_FORMAT
    format_version: Literal[1] = BACKUP_FORMAT_VERSION
    created_at: str
    producer: Literal["codex-usage"] = "codex-usage"
    producer_version: str = Field(min_length=1)
    source_platform: str = Field(min_length=1)
    compression: CompressionManifest
    task_tree: TaskTreeManifest
    source_bytes: int = Field(ge=0)
    physical_file_count: int = Field(ge=0)
    files: list[BackupFileManifest]
    session_index: SessionIndexManifest

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("created_at must be an ISO-8601 timestamp") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("created_at must include a UTC offset")
        return value


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    size_bytes: int
    mtime_ns: int
    source_device: int
    source_inode: int


@dataclass(frozen=True, slots=True)
class BackupSource:
    path: Path
    session_dir: Path
    storage_state: str
    original_relative_path: str
    archive_member: str
    task_id: str
    parent_task_id: str
    usage_role: Literal["root", "subagent"]
    identity: SourceIdentity


@dataclass(frozen=True, slots=True)
class BackupSelection:
    tree_id: str
    root_task_id: str
    title: str
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    recovery_ready: bool
    diagnostics: tuple[str, ...]
    sources: tuple[BackupSource, ...]
    session_index_bytes: bytes
    session_index_entry_count: int

    @property
    def source_bytes(self) -> int:
        return sum(source.identity.size_bytes for source in self.sources)


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive_path: Path
    source_bytes: int
    archive_bytes: int
    file_count: int
    recovery_ready: bool
    warnings: tuple[str, ...]
    archive_sha256: str
    compression: CompressionPreset
    format_version: int = BACKUP_FORMAT_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "archive_path": str(self.archive_path),
            "source_bytes": self.source_bytes,
            "archive_bytes": self.archive_bytes,
            "file_count": self.file_count,
            "recovery_ready": self.recovery_ready,
            "warnings": list(self.warnings),
            "archive_sha256": self.archive_sha256,
            "compression": self.compression,
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    archive_path: Path
    manifest: BackupManifest
    archive_bytes: int
    archive_sha256: str

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self.manifest.task_tree.diagnostics)

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.manifest.format_version,
            "archive_path": str(self.archive_path),
            "source_bytes": self.manifest.source_bytes,
            "archive_bytes": self.archive_bytes,
            "file_count": self.manifest.physical_file_count,
            "recovery_ready": self.manifest.task_tree.recovery_ready,
            "warnings": list(self.warnings),
            "archive_sha256": self.archive_sha256,
            "compression": self.manifest.compression.preset,
        }
