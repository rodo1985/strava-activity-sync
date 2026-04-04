"""FastAPI application factory and shared service wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from strava_activity_sync.api.auth import build_auth_router
from strava_activity_sync.api.health import build_health_router
from strava_activity_sync.api.webhook import build_webhook_router
from strava_activity_sync.config import Settings, get_settings
from strava_activity_sync.logging import configure_logging
from strava_activity_sync.scheduler.jobs import SchedulerService
from strava_activity_sync.services.backfill_service import BackfillService
from strava_activity_sync.services.exporters import GoogleDriveExporter, LocalFilesystemExporter
from strava_activity_sync.services.render_service import RenderService
from strava_activity_sync.services.strava_client import StravaClient
from strava_activity_sync.services.sync_service import SyncService
from strava_activity_sync.storage.db import Database
from strava_activity_sync.storage.repositories import StravaRepository


@dataclass(slots=True)
class AppServices:
    """Service container shared by FastAPI and CLI entrypoints."""

    settings: Settings
    database: Database
    repository: StravaRepository
    strava_client: StravaClient
    render_service: RenderService
    sync_service: SyncService
    backfill_service: BackfillService
    scheduler: SchedulerService


def build_services(settings: Settings | None = None) -> AppServices:
    """Instantiate the service graph used by the application.

    Parameters:
        settings: Optional prebuilt settings object for tests or custom entrypoints.

    Returns:
        AppServices: Fully wired service container used by HTTP and CLI commands.
    """

    resolved_settings = settings or get_settings()
    resolved_settings.ensure_runtime_directories()
    database = Database(resolved_settings.database_path)
    database.initialize()
    repository = StravaRepository(database)
    strava_client = StravaClient(resolved_settings)
    exporter = (
        GoogleDriveExporter(resolved_settings)
        if resolved_settings.enable_drive_export
        else LocalFilesystemExporter(resolved_settings.export_dir)
    )
    render_service = RenderService(exporter, resolved_settings.timezone)
    sync_service = SyncService(
        repository,
        strava_client,
        render_service,
        sync_batch_size=resolved_settings.sync_batch_size,
    )
    backfill_service = BackfillService(sync_service)
    scheduler = SchedulerService(
        sync_service,
        resolved_settings.reconciliation_interval_minutes,
        resolved_settings.reconcile_lookback_days,
    )
    return AppServices(
        settings=resolved_settings,
        database=database,
        repository=repository,
        strava_client=strava_client,
        render_service=render_service,
        sync_service=sync_service,
        backfill_service=backfill_service,
        scheduler=scheduler,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application for the service.

    Parameters:
        settings: Optional prebuilt settings object for tests or custom entrypoints.

    Returns:
        FastAPI: Configured application instance with shared services attached.
    """

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    services = build_services(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Start background jobs and attempt the initial seed sync when appropriate.

        Yields:
            None: Control returns to FastAPI for the application lifetime.
        """

        services.scheduler.start()
        services.sync_service.maybe_run_initial_backfill(services.settings.sync_lookback_days)
        yield
        services.scheduler.shutdown()

    app = FastAPI(title="Strava Activity Sync", lifespan=lifespan)
    app.state.services = services
    app.include_router(build_health_router(services.repository))
    app.include_router(
        build_auth_router(
            services.repository,
            services.strava_client,
            services.sync_service,
            services.settings.sync_lookback_days,
        )
    )
    app.include_router(
        build_webhook_router(
            services.sync_service,
            services.settings.strava_webhook_verify_token,
        )
    )
    return app


app = create_app()
