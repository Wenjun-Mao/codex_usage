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


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    pid: int
    api_version: int
    port: int
    token: str
    started_at: str
    codex_home: str

    @classmethod
    def create(cls, *, port: int, codex_home: Path) -> "AgentDescriptor":
        return cls(
            pid=os.getpid(),
            api_version=AGENT_API_VERSION,
            port=port,
            token=secrets.token_urlsafe(32),
            started_at=datetime.now(UTC).isoformat(),
            codex_home=str(codex_home),
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
    descriptor = AgentDescriptor(
        pid=int(payload["pid"]),
        api_version=int(payload["api_version"]),
        port=int(payload["port"]),
        token=str(payload["token"]),
        started_at=str(payload["started_at"]),
        codex_home=str(payload["codex_home"]),
    )
    if descriptor.api_version != AGENT_API_VERSION:
        raise ValueError(
            f"agent API {descriptor.api_version} is incompatible with client API {AGENT_API_VERSION}"
        )
    if not 1 <= descriptor.port <= 65535 or len(descriptor.token) < 32:
        raise ValueError("agent descriptor contains invalid connection details")
    return descriptor
