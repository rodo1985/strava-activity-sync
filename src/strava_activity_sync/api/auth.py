"""Strava OAuth route wiring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from strava_activity_sync.services.backfill_service import BackfillService
from strava_activity_sync.services.strava_client import StravaClient, StravaClientError
from strava_activity_sync.services.sync_service import SyncService
from strava_activity_sync.storage.repositories import StravaRepository


LOGGER = logging.getLogger(__name__)


def build_auth_router(
    repository: StravaRepository,
    strava_client: StravaClient,
    backfill_service: BackfillService,
    initial_backfill_days: int,
) -> APIRouter:
    """Build OAuth routes for connecting the single athlete account."""

    router = APIRouter(prefix="/auth/strava", tags=["auth"])

    @router.get("/start")
    def start_auth() -> RedirectResponse:
        """Redirect the user to the Strava OAuth consent page."""

        return RedirectResponse(strava_client.build_authorize_url())

    @router.get("/callback")
    def auth_callback(
        code: str = Query(..., description="OAuth code returned by Strava"),
        scope: str | None = Query(default=None, description="Granted Strava scopes"),
    ) -> dict[str, object]:
        """Exchange the OAuth code, store credentials, and trigger the first backfill."""

        try:
            token_bundle = strava_client.exchange_code(code)
            repository.save_tokens(token_bundle)
            profile = strava_client.get_athlete(token_bundle.access_token)
            repository.save_athlete_profile(profile)
            if repository.is_empty():
                backfill_service.backfill_days(initial_backfill_days)
            return {
                "status": "connected",
                "athlete_id": profile.athlete_id,
                "granted_scope": scope or token_bundle.scope,
            }
        except StravaClientError as error:
            LOGGER.exception("Strava OAuth callback failed")
            raise HTTPException(status_code=502, detail=str(error)) from error

    return router

