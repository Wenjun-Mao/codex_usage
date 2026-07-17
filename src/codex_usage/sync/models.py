from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from codex_usage.sync.constants import (
    LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
    LOCAL_BASELINE_STATE_VERSION,
    REMOTE_TRANSFER_FORMAT_VERSION,
)
from codex_usage.sync.identity import (
    require_canonical_thread_id,
    require_remote_index_thread_identity,
)
from codex_usage.sync.model_validation import (
    REMOTE_INDEX_KEYS as _REMOTE_INDEX_KEYS,
    REMOTE_THREAD_ENTRY_KEYS as _REMOTE_THREAD_ENTRY_KEYS,
    require_dict as _require_dict,
    require_int as _require_int,
    require_object as _require_object,
    require_string as _require_string,
    require_string_tuple as _require_string_tuple,
)
from codex_usage.threads import ThreadInfo


ProjectIdentityKind = Literal["git", "path"]


@dataclass(frozen=True)
class ProjectBinding:
    project_key: str
    path: Path
    confirmed_unverified: bool = False


@dataclass(frozen=True)
class ProjectResolutionRequest:
    candidate_roots: tuple[Path, ...] = ()
    bindings: tuple[ProjectBinding, ...] = ()


@dataclass(frozen=True)
class ProjectDestination:
    identity_kind: ProjectIdentityKind
    candidate_roots: tuple[Path, ...]


@dataclass(frozen=True)
class SyncFileSnapshot:
    path: Path | None
    exists: bool
    sha256: str = ""
    size_bytes: int = 0


@dataclass(frozen=True)
class RemoteThreadEntry:
    thread_id: str
    file: str
    source_relative_path: str
    index_entry: dict[str, Any]
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    sha256: str
    size_bytes: int
    session_updated_at: str
    exported_at: str
    source_machine_id: str

    @classmethod
    def from_dict(cls, thread_id: str, value: dict[str, Any]) -> RemoteThreadEntry:
        _require_object(value, _REMOTE_THREAD_ENTRY_KEYS, "remote thread entry")
        return cls(
            thread_id=_require_string(thread_id, "thread id"),
            file=_require_string(value["file"], "file"),
            source_relative_path=_require_string(value["source_relative_path"], "source_relative_path"),
            index_entry=_require_dict(value["index_entry"], "index_entry"),
            project_key=_require_string(value["project_key"], "project_key"),
            project_label=_require_string(value["project_label"], "project_label"),
            project_aliases=_require_string_tuple(value["project_aliases"], "project_aliases"),
            sha256=_require_string(value["sha256"], "sha256"),
            size_bytes=_require_int(value["size_bytes"], "size_bytes"),
            session_updated_at=_require_string(value["session_updated_at"], "session_updated_at"),
            exported_at=_require_string(value["exported_at"], "exported_at"),
            source_machine_id=_require_string(value["source_machine_id"], "source_machine_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "source_relative_path": self.source_relative_path,
            "index_entry": dict(self.index_entry),
            "project_key": self.project_key,
            "project_label": self.project_label,
            "project_aliases": list(self.project_aliases),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "session_updated_at": self.session_updated_at,
            "exported_at": self.exported_at,
            "source_machine_id": self.source_machine_id,
        }


@dataclass(frozen=True)
class RemoteIndex:
    format_version: int
    updated_at: str
    threads: dict[str, RemoteThreadEntry]

    def __post_init__(self) -> None:
        self._validate_contract()

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        expected_format_version: int = REMOTE_TRANSFER_FORMAT_VERSION,
    ) -> RemoteIndex:
        _require_object(value, _REMOTE_INDEX_KEYS, "remote index")
        format_version = _require_int(value["format_version"], "format_version")
        if format_version != expected_format_version:
            raise ValueError(f"format_version must be {expected_format_version}")
        raw_threads = _require_dict(value["threads"], "threads")
        threads: dict[str, RemoteThreadEntry] = {}
        for thread_id, raw_entry in raw_threads.items():
            if not isinstance(thread_id, str):
                raise ValueError("remote index thread ids must be strings")
            threads[thread_id] = RemoteThreadEntry.from_dict(
                thread_id,
                _require_dict(raw_entry, f"thread {thread_id!r}"),
            )
        return cls(
            format_version=format_version,
            updated_at=_require_string(value["updated_at"], "updated_at"),
            threads=threads,
        )

    def to_dict(self) -> dict[str, Any]:
        self._validate_contract()
        return {
            "format_version": self.format_version,
            "updated_at": self.updated_at,
            "threads": {thread_id: entry.to_dict() for thread_id, entry in self.threads.items()},
        }

    def _validate_contract(self) -> None:
        supported_versions = {
            LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
            REMOTE_TRANSFER_FORMAT_VERSION,
        }
        if self.format_version not in supported_versions:
            versions = ", ".join(str(version) for version in sorted(supported_versions))
            raise ValueError(f"format_version must be one of: {versions}")
        for thread_id, entry in self.threads.items():
            if not isinstance(entry, RemoteThreadEntry):
                raise ValueError(
                    f"remote index thread {thread_id!r} must be a RemoteThreadEntry"
                )
            require_remote_index_thread_identity(
                thread_id,
                entry.thread_id,
                entry.index_entry,
            )


@dataclass(frozen=True)
class RemoteInventory:
    persisted_index: RemoteIndex
    index: RemoteIndex
    index_snapshot: SyncFileSnapshot
    files: dict[str, SyncFileSnapshot]
    repaired_thread_ids: tuple[str, ...]
    issues: tuple[SyncIssue, ...]


@dataclass(frozen=True)
class LocalInventory:
    session_dirs: tuple[Path, ...]
    threads: dict[str, ThreadInfo]
    index_entries: dict[str, dict[str, Any]]
    discovered_count: int
    project_roots: dict[str, tuple[Path, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for thread_id, thread in self.threads.items():
            require_canonical_thread_id(
                thread_id,
                f"local sync inventory thread_id key {thread_id!r}",
            )
            require_canonical_thread_id(
                thread.thread_id,
                f"local sync inventory thread {thread_id!r}.thread_id",
            )
            if thread_id != thread.thread_id:
                raise ValueError(
                    "local sync inventory thread mapping key must match ThreadInfo.thread_id"
                )


@dataclass(frozen=True)
class LocalSyncState:
    thread_id: str
    sync_dir_fingerprint: str
    base_sha256: str
    base_size_bytes: int
    base_updated_at: str
    last_remote_sha256: str
    last_local_sha256: str
    source_relative_path: str
    project_key: str
    project_label: str
    synced_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LocalSyncState | None:
        sync_version = value.get("sync_version")
        if type(sync_version) is not int or sync_version != LOCAL_BASELINE_STATE_VERSION:
            return None
        thread_id = str(value.get("thread_id") or "").strip()
        fingerprint = str(value.get("sync_dir_fingerprint") or "").strip()
        base_sha256 = str(value.get("base_sha256") or "").strip()
        if not thread_id or not fingerprint or not base_sha256:
            return None
        return cls(
            thread_id=thread_id,
            sync_dir_fingerprint=fingerprint,
            base_sha256=base_sha256,
            base_size_bytes=int(value.get("base_size_bytes") or 0),
            base_updated_at=str(value.get("base_updated_at") or ""),
            last_remote_sha256=str(value.get("last_remote_sha256") or ""),
            last_local_sha256=str(value.get("last_local_sha256") or ""),
            source_relative_path=str(value.get("source_relative_path") or ""),
            project_key=str(value.get("project_key") or ""),
            project_label=str(value.get("project_label") or ""),
            synced_at=str(value.get("synced_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sync_version": LOCAL_BASELINE_STATE_VERSION,
            "thread_id": self.thread_id,
            "sync_dir_fingerprint": self.sync_dir_fingerprint,
            "base_sha256": self.base_sha256,
            "base_size_bytes": self.base_size_bytes,
            "base_updated_at": self.base_updated_at,
            "last_remote_sha256": self.last_remote_sha256,
            "last_local_sha256": self.last_local_sha256,
            "source_relative_path": self.source_relative_path,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "synced_at": self.synced_at,
        }


@dataclass(frozen=True)
class SyncIssue:
    code: str
    message: str
    thread_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "thread_id": self.thread_id}


@dataclass(frozen=True)
class SyncPlanItem:
    thread_id: str
    state: str
    action: str
    reason: str
    local: SyncFileSnapshot
    remote: SyncFileSnapshot
    base_sha256: str
    updated_at: str
    source_relative_path: str
    project_key: str
    project_label: str
    memory_database_rows: int
    expected_remote_entry: RemoteThreadEntry | None
    local_project_root: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "thread_id": self.thread_id,
            "state": self.state,
            "action": self.action,
            "reason": self.reason,
            "local_path": str(self.local.path) if self.local.path else "",
            "remote_path": str(self.remote.path) if self.remote.path else "",
            "local_sha256": self.local.sha256,
            "remote_sha256": self.remote.sha256,
            "base_sha256": self.base_sha256,
            "updated_at": self.updated_at,
            "source_relative_path": self.source_relative_path,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "memory_database_rows": self.memory_database_rows,
        }
        if self.memory_database_rows:
            value["memory_note"] = "memory database rows detected, not synced by this beta"
        return value


@dataclass(frozen=True)
class SyncPlan:
    items: tuple[SyncPlanItem, ...]
    issues: tuple[SyncIssue, ...]
    discovered_count: int
    remote_count: int
    selected_count: int

    def __post_init__(self) -> None:
        mismatched_issue_items = [
            item.thread_id
            for item in self.items
            if (item.state == "issue") != (item.action == "issue")
        ]
        if mismatched_issue_items:
            thread_ids = ", ".join(sorted(mismatched_issue_items))
            raise ValueError(
                f"Sync plan item state and action must both be 'issue' for thread ids: {thread_ids}"
            )
        issue_thread_ids = {issue.thread_id for issue in self.issues}
        missing_diagnostics = [
            item.thread_id
            for item in self.items
            if item.action == "issue" and item.thread_id not in issue_thread_ids
        ]
        if missing_diagnostics:
            thread_ids = ", ".join(sorted(missing_diagnostics))
            raise ValueError(f"issue-action items require a structured SyncIssue for thread ids: {thread_ids}")

    def expected_remote_entries(self) -> dict[str, RemoteThreadEntry | None]:
        return {item.thread_id: item.expected_remote_entry for item in self.items}

    def expected_remote_snapshots(self) -> dict[str, SyncFileSnapshot]:
        return {item.thread_id: item.remote for item in self.items}

    @property
    def has_conflicts(self) -> bool:
        return any(item.action == "conflict" for item in self.items)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    @property
    def blocks_execution(self) -> bool:
        return self.has_conflicts or any(item.action == "issue" for item in self.items)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "threads": [item.to_dict() for item in self.items],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class SyncProgressEvent:
    type: str
    phase: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "phase": self.phase}


@dataclass(frozen=True)
class SyncCounts:
    discovered: int
    selected: int
    remote: int
    pulled: int
    pushed: int
    unchanged: int
    conflicts: int
    issues: int

    def to_dict(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "selected": self.selected,
            "remote": self.remote,
            "pulled": self.pulled,
            "pushed": self.pushed,
            "unchanged": self.unchanged,
            "conflicts": self.conflicts,
            "issues": self.issues,
        }


@dataclass(frozen=True)
class SyncTimings:
    discovery: int
    planning: int
    pull: int
    push: int
    index: int
    total: int

    def to_dict(self) -> dict[str, int]:
        return {
            "discovery": self.discovery,
            "planning": self.planning,
            "pull": self.pull,
            "push": self.push,
            "index": self.index,
            "total": self.total,
        }


@dataclass(frozen=True)
class SyncRunResult:
    outcome: str
    counts: SyncCounts
    timings_ms: SyncTimings
    threads: tuple[SyncPlanItem, ...]
    pulled: tuple[str, ...]
    pushed: tuple[str, ...]
    issues: tuple[SyncIssue, ...]

    @classmethod
    def blocked(cls, plan: SyncPlan, timings: SyncTimings) -> SyncRunResult:
        outcome = "conflict" if plan.has_conflicts else "issue"
        return cls._from_plan(outcome, plan, (), (), plan.issues, timings)

    @classmethod
    def blocked_with_issues(
        cls,
        plan: SyncPlan,
        issues: tuple[SyncIssue, ...],
        timings: SyncTimings,
    ) -> SyncRunResult:
        return cls._from_plan("issue", plan, (), (), (*plan.issues, *issues), timings)

    @classmethod
    def failed(
        cls,
        plan: SyncPlan,
        runtime_issue: SyncIssue,
        pulled: tuple[str, ...],
        pushed: tuple[str, ...],
        timings: SyncTimings,
    ) -> SyncRunResult:
        issues = (*plan.issues, runtime_issue)
        return cls._from_plan("issue", plan, pulled, pushed, issues, timings)

    @classmethod
    def completed(
        cls,
        plan: SyncPlan,
        pulled: tuple[str, ...],
        pushed: tuple[str, ...],
        timings: SyncTimings,
    ) -> SyncRunResult:
        return cls._from_plan("completed", plan, pulled, pushed, plan.issues, timings)

    @classmethod
    def _from_plan(
        cls,
        outcome: str,
        plan: SyncPlan,
        pulled: tuple[str, ...],
        pushed: tuple[str, ...],
        issues: tuple[SyncIssue, ...],
        timings: SyncTimings,
    ) -> SyncRunResult:
        counts = SyncCounts(
            discovered=plan.discovered_count,
            selected=plan.selected_count,
            remote=plan.remote_count,
            pulled=len(pulled),
            pushed=len(pushed),
            unchanged=sum(item.action == "none" for item in plan.items),
            conflicts=sum(item.action == "conflict" for item in plan.items),
            issues=len(issues),
        )
        return cls(outcome, counts, timings, plan.items, pulled, pushed, issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "counts": self.counts.to_dict(),
            "timings_ms": self.timings_ms.to_dict(),
            "threads": [thread.to_dict() for thread in self.threads],
            "pulled": list(self.pulled),
            "pushed": list(self.pushed),
            "issues": [issue.to_dict() for issue in self.issues],
        }
