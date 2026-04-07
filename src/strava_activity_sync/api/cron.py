"""Cron endpoint wiring for serverless deployments."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException

from strava_activity_sync.services.strava_client import StravaClientError
from strava_activity_sync.services.sync_service import SyncService


LOGGER = logging.getLogger(__name__)


def build_cron_router(
    sync_service: SyncService,
    cron_secret: str,
    lookback_days: int,
) -> APIRouter:
    """Build the cron router used by Vercel scheduled invocations.

    Parameters:
        sync_service: Sync service used to run the recent-first reconciliation.
        cron_secret: Shared secret expected from Vercel cron requests.
        lookback_days: Recent-window size used during reconciliation.

    Returns:
        APIRouter: Router exposing the reconciliation endpoint.
    """

    router = APIRouter(prefix="/cron", tags=["cron"])

    @router.get("/reconcile")
    def reconcile_cron(authorization: str | None = Header(default=None)) -> dict[str, object]:
        """Run one reconciliation cycle when invoked by a trusted scheduler.

        Parameters:
            authorization: Authorization header expected to contain the Vercel
                `CRON_SECRET` bearer token.

        Returns:
            dict[str, object]: Sync summary for the invoked reconciliation cycle.

        Raises:
            HTTPException: Raised when the cron secret is missing or when the
                Strava sync fails during the scheduled invocation.
        """

        if cron_secret:
            expected = f"Bearer {cron_secret}"
            if authorization != expected:
                raise HTTPException(status_code=401, detail="Unauthorized cron invocation.")

        try:
            result = sync_service.reconcile(lookback_days=lookback_days)
            return {
                "status": "ok",
                "processed_activity_ids": result.processed_activity_ids,
                "exported_paths": result.exported_paths,
            }
        except StravaClientError as error:
            LOGGER.exception("Scheduled reconcile failed")
            raise HTTPException(status_code=502, detail=str(error)) from error

    return router
