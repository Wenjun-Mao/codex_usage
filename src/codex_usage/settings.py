from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class AppSettings(BaseSettings):
    sessions_dir: Path | None = None
    timezone: str | None = None
    subscription_usd: float | None = None
    output_dir: Path = Path("output")

    model_config = SettingsConfigDict(
        env_prefix="CODEX_USAGE_",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, file_secret_settings, env_settings, dotenv_settings


@lru_cache
def get_settings() -> AppSettings:
    secrets_dir = Path("/run/secrets")
    if secrets_dir.is_dir():
        return AppSettings(_secrets_dir=secrets_dir)
    return AppSettings()
