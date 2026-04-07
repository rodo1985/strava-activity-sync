"""Application configuration models."""

from __future__ import annotations

from functools import lru_cache
import os
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
    deployment_target: str = "local"
    storage_backend: str = "sqlite"
    export_backend: str = "local"
    sync_lookback_days: int = 30
    reconciliation_interval_minutes: int = 16
    reconcile_lookback_days: int = 14
    sync_batch_size: int = 32
    strava_request_timeout_seconds: int = 30
    strava_verify_ssl: bool = True
    strava_ca_bundle_path: str = ""
    cron_secret: str = ""
    vercel_blob_state_path: str = "strava/state/strava-state.json"
    vercel_blob_export_prefix: str = "strava/exports"
    vercel_blob_access: str = "private"
    enable_drive_export: bool = False
    google_drive_folder_id: str = ""
    google_drive_service_account_json: str = ""
    apex_supabase_url: str = ""
    apex_supabase_service_role_key: str = ""
    apex_supabase_schema: str = "public"
    vite_supabase_url: str = ""
    vite_supabase_anon_key: str = ""
    vite_supabase_user_id: str = "sergio"
    supabase_db_host: str = ""
    supabase_db_port: int = 5432
    supabase_db_name: str = "postgres"
    supabase_db_user: str = "postgres"
    supabase_db_password: str = ""
    supabase_db_sslmode: str = "require"
    supabase_storage_bucket: str = "strava-context"

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

    @property
    def is_vercel(self) -> bool:
        """Return whether the app is configured to run on Vercel.

        Returns:
            bool: `True` when the deployment target is Vercel or when the
                platform environment variable is present.
        """

        return self.deployment_target.lower() == "vercel" or os.getenv("VERCEL") == "1"

    @property
    def has_apex_supabase_config(self) -> bool:
        """Return whether enough Supabase settings exist for APEX projection.

        Returns:
            bool: `True` when the backend URL and service-role key are present.

        Example:
            >>> settings = AppConfig(apex_supabase_url="https://x.supabase.co", apex_supabase_service_role_key="key")
            >>> settings.has_apex_supabase_config
            True
        """

        return bool(self.apex_supabase_url and self.apex_supabase_service_role_key)


Settings = AppConfig


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Return a cached settings instance for runtime entrypoints.

    Returns:
        AppConfig: The cached singleton settings object for the current process.
    """

    return AppConfig()
