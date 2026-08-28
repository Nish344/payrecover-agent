from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-backed settings. Keys never have defaults; secrets stay wrapped."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str
    razorpay_key_secret: SecretStr
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model: str = "claude-sonnet-4-5"
    kill_switch: bool = False
    razorpay_timeout_seconds: float = Field(default=10.0, gt=0)
    razorpay_read_retries: int = Field(default=3, ge=1, le=5)
    db_path: Path = Path("data/payrecover.db")

    @field_validator("razorpay_key_id")
    @classmethod
    def _strip_key_id(cls, value: str) -> str:
        return value.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
