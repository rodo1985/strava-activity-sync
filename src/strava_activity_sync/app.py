"""FastAPI application factory and shared service wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

import logging
from threading import Thread

from fastapi import FastAPI

from strava_activity_sync.api.auth import build_auth_router
from strava_activity_sync.api.cron import build_cron_router
from strava_activity_sync.api.health import build_health_router
from strava_activity_sync.api.webhook import build_webhook_router
from strava_activity_sync.config import Settings, get_settings
from strava_activity_sync.logging import configure_logging
from strava_activity_sync.scheduler.jobs import SchedulerService
from strava_activity_sync.services.backfill_service import BackfillService
from strava_activity_sync.services.apex_supabase_projector import ApexSupabaseProjector
from strava_activity_sync.services.exporters import (
    GoogleDriveExporter,
    LocalFilesystemExporter,
    VercelBlobExporter,
)
from strava_activity_sync.services.render_service import RenderService
from strava_activity_sync.services.strava_client import StravaClient
from strava_activity_sync.services.sync_service import SyncService
from strava_activity_sync.storage.blob_repository import VercelBlobStravaRepository
from strava_activity_sync.storage.db import Database
from strava_activity_sync.storage.repositories import StravaRepository, StravaRepositoryProtocol


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AppServices:
    """Service container shared by FastAPI and CLI entrypoints."""

    settings: Settings
    database: Database | None
    repository: StravaRepositoryProtocol
    strava_client: StravaClient
    render_service: RenderService
    sync_service: SyncService
    backfill_service: BackfillService
    scheduler: SchedulerService
    apex_projector: ApexSupabaseProjector | None


def _run_startup_sync_safely(sync_service: SyncService, lookback_days: int) -> None:
    """Run startup sync in a background thread without crashing the API process.

    Parameters:
        sync_service: Sync service used to perform the startup collection.
        lookback_days: Trailing window used for the initial recent-first pass.

    Returns:
        None: The sync runs for its side effects and logs failures instead of raising.
    """

    try:
        sync_service.run_startup_sync(lookback_days)
    except Exception:
        LOGGER.exception("Startup sync failed; the API will continue serving and retry on schedule.")


def build_services(settings: Settings | None = None) -> AppServices:
    """Instantiate the service graph used by the application.

    Parameters:
        settings: Optional prebuilt settings object for tests or custom entrypoints.

    Returns:
        AppServices: Fully wired service container used by HTTP and CLI commands.
    """

    resolved_settings = settings or get_settings()
    resolved_settings.ensure_runtime_directories()
    database: Database | None = None
    if resolved_settings.storage_backend == "vercel_blob":
        repository: StravaRepositoryProtocol = VercelBlobStravaRepository(resolved_settings)
    else:
        database = Database(resolved_settings.database_path)
        database.initialize()
        repository = StravaRepository(database)
    strava_client = StravaClient(resolved_settings)
    if resolved_settings.enable_drive_export:
        exporter = GoogleDriveExporter(resolved_settings)
    elif resolved_settings.export_backend == "vercel_blob":
        exporter = VercelBlobExporter(resolved_settings)
    else:
        exporter = LocalFilesystemExporter(resolved_settings.export_dir)
    render_service = RenderService(exporter, resolved_settings.timezone)
    apex_projector = (
        ApexSupabaseProjector(resolved_settings) if resolved_settings.has_apex_supabase_config else None
    )
    sync_service = SyncService(
        repository,
        strava_client,
        render_service,
        sync_batch_size=resolved_settings.sync_batch_size,
        apex_projector=apex_projector,
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
        apex_projector=apex_projector,
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

        if not services.settings.is_vercel:
            services.scheduler.start()
            # Startup sync should improve freshness, but it should never prevent the API
            # from serving health checks or later scheduled retries.
            startup_thread = Thread(
                target=_run_startup_sync_safely,
                args=(services.sync_service, services.settings.sync_lookback_days),
                name="startup-sync",
                daemon=True,
            )
            startup_thread.start()
        yield
        if not services.settings.is_vercel:
            services.scheduler.shutdown()

    app = FastAPI(title="Strava Activity Sync", lifespan=lifespan)
    app.state.services = services
    app.include_router(build_health_router(services.repository))
    app.include_router(
        build_cron_router(
            services.sync_service,
            services.settings.cron_secret,
            services.settings.reconcile_lookback_days,
        )
    )
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
