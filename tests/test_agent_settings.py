from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_usage.agent_settings import (
    AgentSettings,
    load_agent_settings,
    save_agent_settings,
)


def test_settings_round_trip_manual_only_and_custom_home(tmp_path: Path) -> None:
    target = tmp_path / "config" / "settings.json"
    home = tmp_path / "custom-codex"
    settings = AgentSettings(
        codex_home=str(home),
        capture_interval_minutes=None,
        background_capture=True,
        daily_update_checks=True,
        onboarding_complete=True,
        native_onboarding_complete=True,
        theme="night",
    )

    save_agent_settings(settings, target)

    loaded = load_agent_settings(target)
    assert loaded.codex_home == str(home.resolve())
    assert loaded.manual_only is True
    assert loaded.background_capture is True
    assert loaded.onboarding_complete is True
    assert loaded.native_onboarding_complete is True
    assert json.loads(target.read_text())["schema_version"] == 1
    if os.name != "nt":
        assert target.parent.stat().st_mode & 0o777 == 0o700
        assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("interval", [0, 1441])
def test_settings_reject_out_of_range_interval(interval: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 1440"):
        AgentSettings(
            codex_home="~/.codex", capture_interval_minutes=interval
        ).validated()


@pytest.mark.parametrize(
    "field",
    [
        "background_capture",
        "daily_update_checks",
        "onboarding_complete",
        "native_onboarding_complete",
        "auto_project_transitions",
    ],
)
def test_settings_reject_truthy_non_boolean_values(
    tmp_path: Path,
    field: str,
) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    payload = {
        "schema_version": 1,
        "codex_home": str(home),
        "capture_interval_minutes": 15,
        "background_capture": False,
        "daily_update_checks": False,
        "onboarding_complete": False,
        "native_onboarding_complete": False,
        "timezone": None,
        "theme": "auto",
        "auto_project_transitions": True,
        "transfer_folder": "",
    }
    payload[field] = "false"
    target = tmp_path / "settings.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="boolean setting"):
        load_agent_settings(target)


def test_legacy_core_onboarding_does_not_complete_native_consent(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex_home": str(home),
                "onboarding_complete": True,
            }
        ),
        encoding="utf-8",
    )

    settings = load_agent_settings(target)

    assert settings.onboarding_complete is True
    assert settings.native_onboarding_complete is False
