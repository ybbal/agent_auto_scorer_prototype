from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_CORP"
    gigachat_model: str = "GigaChat-2"
    gigachat_verify_ssl_certs: bool = False
    gigachat_timeout_seconds: float = Field(default=30.0, gt=0)

    telegram_bot_token: SecretStr | None = None
    telegram_timeout_seconds: float = Field(default=30.0, gt=0)
    state_db_path: Path = PROJECT_ROOT / "var" / "agent.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_file_path: Path = PROJECT_ROOT / "var" / "logs" / "agent.log"
    log_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    log_backup_count: int = Field(default=5, ge=1, le=100)
    score_csv_path: Path = PROJECT_ROOT / "resources" / "sample_scores_table_auto_349653.csv"
    feature_mapping_path: Path = PROJECT_ROOT / "resources" / "feature_mappings.json"
    max_factors_per_direction: int = Field(default=3, ge=1, le=10)
