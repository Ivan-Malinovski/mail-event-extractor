"""Configuration management using pydantic-settings."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PCB_",
        extra="ignore",
    )

    # Web UI
    host: str = "0.0.0.0"
    port: int = 8080
    web_auth_enabled: bool = False
    web_password: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///:memory:"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_retention_days: int = 30


settings = Settings()
