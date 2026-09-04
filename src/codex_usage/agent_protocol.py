from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
)


AGENT_API_VERSION = 1
MAX_API_REQUEST_BYTES = 2 * 1024 * 1024
_PROCESS_OWNERS = frozenset({"background", "transient", "unknown"})


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    pid: int
    api_version: int
    port: int
    token: str
    started_at: str
    codex_home: str
    # Older collectors did not declare their lifetime. Clients may connect to
    # them, but must not infer that they are safe to stop.
    process_owner: str = "unknown"
    parent_pid: int | None = None

    @classmethod
    def create(
        cls,
        *,
        port: int,
        codex_home: Path,
        process_owner: str,
        parent_pid: int | None,
    ) -> "AgentDescriptor":
        _validate_process_owner(process_owner, parent_pid)
        return cls(
            pid=os.getpid(),
            api_version=AGENT_API_VERSION,
            port=port,
            token=secrets.token_urlsafe(32),
            started_at=datetime.now(UTC).isoformat(),
            codex_home=str(codex_home),
            process_owner=process_owner,
            parent_pid=parent_pid,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_agent_descriptor(path: Path, descriptor: AgentDescriptor) -> None:
    ensure_private_directory(path.parent)
    payload = json.dumps(descriptor.to_dict(), indent=2, sort_keys=True) + "\n"
    descriptor_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor_fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        ensure_private_file(temporary)
        os.replace(temporary, path)
        ensure_private_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_agent_descriptor(path: Path) -> AgentDescriptor:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("agent descriptor must be a JSON object")
    process_owner = str(payload.get("process_owner", "unknown"))
    raw_parent_pid = payload.get("parent_pid")
    parent_pid = _optional_process_id(raw_parent_pid)
    _validate_process_owner(process_owner, parent_pid)
    descriptor = AgentDescriptor(
        pid=int(payload["pid"]),
        api_version=int(payload["api_version"]),
        port=int(payload["port"]),
        token=str(payload["token"]),
        started_at=str(payload["started_at"]),
        codex_home=str(payload["codex_home"]),
        process_owner=process_owner,
        parent_pid=parent_pid,
    )
    if descriptor.api_version != AGENT_API_VERSION:
        raise ValueError(
            f"agent API {descriptor.api_version} is incompatible with client API {AGENT_API_VERSION}"
        )
    if not 1 <= descriptor.port <= 65535 or len(descriptor.token) < 32:
        raise ValueError("agent descriptor contains invalid connection details")
    return descriptor


def _optional_process_id(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("agent descriptor parent PID must be an integer")
    process_id = int(value)
    if process_id <= 0:
        raise ValueError("agent descriptor parent PID must be greater than zero")
    return process_id


def _validate_process_owner(process_owner: str, parent_pid: int | None) -> None:
    if process_owner not in _PROCESS_OWNERS:
        raise ValueError("agent descriptor has an unsupported process owner")
    if process_owner == "transient" and parent_pid is None:
        raise ValueError("transient agent descriptors require a parent PID")
    if process_owner != "transient" and parent_pid is not None:
        raise ValueError("only transient agent descriptors may have a parent PID")
