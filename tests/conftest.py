"""Shared pytest fixtures for the Strava activity sync test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from strava_activity_sync.config import Settings
from strava_activity_sync.services.exporters import LocalFilesystemExporter
from strava_activity_sync.services.render_service import RenderService
from strava_activity_sync.storage.db import Database
from strava_activity_sync.storage.repositories import StravaRepository


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture by filename."""

    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Return an isolated settings object for each test."""

    return Settings(
        app_base_url="http://localhost:8000",
        app_host="127.0.0.1",
        app_port=8000,
        log_level="INFO",
        strava_client_id="client-id",
        strava_client_secret="client-secret",
        strava_webhook_verify_token="verify-token",
        strava_webhook_callback_url="http://localhost:8000/webhooks/strava",
        strava_redirect_uri="http://localhost:8000/auth/strava/callback",
        strava_scopes="read,activity:read_all,profile:read_all",
        database_path=tmp_path / "db" / "test.sqlite",
        export_dir=tmp_path / "exports",
        timezone="Europe/Madrid",
        sync_lookback_days=365,
        reconciliation_interval_minutes=60,
        reconcile_lookback_days=30,
        strava_request_timeout_seconds=5,
        enable_drive_export=False,
        google_drive_folder_id="",
        google_drive_service_account_json="",
    )


@pytest.fixture()
def repository(settings: Settings) -> StravaRepository:
    """Return an initialized repository backed by a temporary SQLite database."""

    database = Database(settings.database_path)
    database.initialize()
    return StravaRepository(database)


@pytest.fixture()
def render_service(settings: Settings) -> RenderService:
    """Return a render service writing to a temporary export directory."""

    exporter = LocalFilesystemExporter(settings.export_dir)
    return RenderService(exporter, settings.timezone)
