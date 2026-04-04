"""Application configuration models."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Store all runtime configuration for the application.

    Returns:
        AppConfig: A populated settings object sourced from `.env` and defaults.

    Example:
        >>> settings = AppConfig()
        >>> settings.sync_batch_size
        32
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_base_url: str = "http://127.0.0.1:8000"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_webhook_verify_token: str = ""
    strava_webhook_callback_url: str = ""
    strava_redirect_uri: str = "http://127.0.0.1:8000/auth/strava/callback"
    strava_scopes: str = "read,activity:read_all,profile:read_all"
    database_path: Path = Field(default=Path("data/db/strava_activity_sync.sqlite3"))
    export_dir: Path = Field(default=Path("data/exports"))
    timezone: str = "Europe/Madrid"
    sync_lookback_days: int = 30
    reconciliation_interval_minutes: int = 16
    reconcile_lookback_days: int = 14
    sync_batch_size: int = 32
    strava_request_timeout_seconds: int = 30
    enable_drive_export: bool = False
    google_drive_folder_id: str = ""
    google_drive_service_account_json: str = ""

    def ensure_runtime_directories(self) -> None:
        """Create directories needed by SQLite and export artifacts.

        Returns:
            None: The directories are created in place when missing.

        Raises:
            OSError: Propagates filesystem errors when directories cannot be created.
        """

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    @property
    def strava_api_base_url(self) -> str:
        """Return the base URL for the Strava REST API.

        Returns:
            str: The shared Strava REST API base URL.
        """

        return "https://www.strava.com/api/v3"

    @property
    def strava_oauth_base_url(self) -> str:
        """Return the base URL for Strava OAuth flows.

        Returns:
            str: The shared Strava OAuth base URL.
        """

        return "https://www.strava.com/oauth"

    @property
    def scope_list(self) -> list[str]:
        """Parse the configured OAuth scopes into a list.

        Returns:
            list[str]: Individual non-empty OAuth scopes in configured order.
        """

        return [scope.strip() for scope in self.strava_scopes.split(",") if scope.strip()]


Settings = AppConfig


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Return a cached settings instance for runtime entrypoints.

    Returns:
        AppConfig: The cached singleton settings object for the current process.
    """

    return AppConfig()
