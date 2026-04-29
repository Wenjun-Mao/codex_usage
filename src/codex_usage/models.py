from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


UNKNOWN = "unknown"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "TokenUsage":
        data = data or {}
        return cls(
            input_tokens=_as_int(data.get("input_tokens")),
            cached_input_tokens=_as_int(data.get("cached_input_tokens")),
            output_tokens=_as_int(data.get("output_tokens")),
            reasoning_output_tokens=_as_int(data.get("reasoning_output_tokens")),
            total_tokens=_as_int(data.get("total_tokens")),
        )

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def positive_delta(self, previous: "TokenUsage | None") -> "TokenUsage | None":
        if previous is None:
            return self if self.total_tokens > 0 else None

        total_delta = self.total_tokens - previous.total_tokens
        if total_delta <= 0:
            return None

        return TokenUsage(
            input_tokens=max(0, self.input_tokens - previous.input_tokens),
            cached_input_tokens=max(0, self.cached_input_tokens - previous.cached_input_tokens),
            output_tokens=max(0, self.output_tokens - previous.output_tokens),
            reasoning_output_tokens=max(0, self.reasoning_output_tokens - previous.reasoning_output_tokens),
            total_tokens=total_delta,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class SessionMetadata:
    session_id: str
    file_path: Path
    timestamp: datetime | None = None
    cwd: str = ""
    originator: str = ""
    source: str = ""
    cli_version: str = ""
    model_provider: str = ""
    git_repository_url: str = ""
    git_branch: str = ""
    git_commit_hash: str = ""


@dataclass(frozen=True)
class UsageRecord:
    timestamp: datetime
    usage: TokenUsage
    session_id: str
    file_path: Path
    model: str = UNKNOWN
    turn_id: str = ""
    effort: str = ""
    collaboration_mode: str = ""
    project_key: str = UNKNOWN
    project_label: str = UNKNOWN
    cwd: str = ""
    git_repository_url: str = ""
    git_branch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "file_path": str(self.file_path),
            "model": self.model,
            "turn_id": self.turn_id,
            "effort": self.effort,
            "collaboration_mode": self.collaboration_mode,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "cwd": self.cwd,
            "git_repository_url": self.git_repository_url,
            "git_branch": self.git_branch,
            "usage": self.usage.to_dict(),
        }


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
