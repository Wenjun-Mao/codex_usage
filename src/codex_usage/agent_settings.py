from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from codex_usage.agent_paths import default_codex_home, settings_path
from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
)


SETTINGS_SCHEMA_VERSION = 1
DEFAULT_CAPTURE_INTERVAL_MINUTES = 15
MIN_CAPTURE_INTERVAL_MINUTES = 1
MAX_CAPTURE_INTERVAL_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True)
class AgentSettings:
    codex_home: str
    capture_interval_minutes: int | None = DEFAULT_CAPTURE_INTERVAL_MINUTES
    background_capture: bool = False
    daily_update_checks: bool = False
    onboarding_complete: bool = False
    timezone: str | None = None
    theme: str = "auto"
    auto_project_transitions: bool = True
    transfer_folder: str = ""
    schema_version: int = SETTINGS_SCHEMA_VERSION

    @property
    def manual_only(self) -> bool:
        return self.capture_interval_minutes is None

    def validated(self) -> "AgentSettings":
        home = str(Path(self.codex_home).expanduser().resolve())
        interval = self.capture_interval_minutes
        if interval is not None and not (
            MIN_CAPTURE_INTERVAL_MINUTES <= interval <= MAX_CAPTURE_INTERVAL_MINUTES
        ):
            raise ValueError(
                "capture interval must be Manual Only or between 1 and 1440 minutes"
            )
        if self.theme not in {"auto", "day", "night"}:
            raise ValueError(f"unsupported theme: {self.theme}")
        if self.schema_version != SETTINGS_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported settings schema {self.schema_version}; expected {SETTINGS_SCHEMA_VERSION}"
            )
        return replace(self, codex_home=home)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_agent_settings() -> AgentSettings:
    return AgentSettings(codex_home=str(default_codex_home())).validated()


def load_agent_settings(path: Path | None = None) -> AgentSettings:
    target = path or settings_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_agent_settings()
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read Codex Usage settings: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Codex Usage settings must be a JSON object")
    try:
        return AgentSettings(
            codex_home=str(payload["codex_home"]),
            capture_interval_minutes=_optional_int(
                payload.get(
                    "capture_interval_minutes", DEFAULT_CAPTURE_INTERVAL_MINUTES
                )
            ),
            background_capture=_boolean(payload.get("background_capture", False)),
            daily_update_checks=_boolean(payload.get("daily_update_checks", False)),
            onboarding_complete=_boolean(payload.get("onboarding_complete", False)),
            timezone=_optional_string(payload.get("timezone")),
            theme=str(payload.get("theme", "auto")),
            auto_project_transitions=_boolean(
                payload.get("auto_project_transitions", True)
            ),
            transfer_folder=str(payload.get("transfer_folder", "")),
            schema_version=int(payload.get("schema_version", 0)),
        ).validated()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid Codex Usage settings: {exc}") from exc


def save_agent_settings(
    settings: AgentSettings,
    path: Path | None = None,
) -> Path:
    validated = settings.validated()
    target = path or settings_path()
    ensure_private_directory(target.parent)
    encoded = json.dumps(validated.to_dict(), indent=2, sort_keys=True) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        ensure_private_file(temporary)
        os.replace(temporary, target)
        ensure_private_file(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("boolean is not a capture interval")
    return int(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("boolean setting must be true or false")
    return value
