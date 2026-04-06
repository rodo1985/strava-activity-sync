"""Strava OAuth route wiring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from strava_activity_sync.services.strava_client import StravaClient, StravaClientError
from strava_activity_sync.services.sync_service import SyncService
from strava_activity_sync.storage.repositories import StravaRepository


LOGGER = logging.getLogger(__name__)


def build_auth_router(
    repository: StravaRepository,
    strava_client: StravaClient,
    sync_service: SyncService,
    initial_backfill_days: int,
) -> APIRouter:
    """Build OAuth routes for connecting the single athlete account.

    Parameters:
        repository: Repository used to persist tokens and the athlete profile.
        strava_client: Strava OAuth client wrapper.
        sync_service: Sync service used for the bounded first-run seed sync.
        initial_backfill_days: Trailing window used for the initial local seed.

    Returns:
        APIRouter: OAuth router mounted under `/auth/strava`.
    """

    router = APIRouter(prefix="/auth/strava", tags=["auth"])

    @router.get("/start")
    def start_auth() -> RedirectResponse:
        """Redirect the user to the Strava OAuth consent page.

        Returns:
            RedirectResponse: Redirect to Strava's authorization screen.
        """

        return RedirectResponse(strava_client.build_authorize_url())

    @router.get("/callback")
    def auth_callback(
        code: str = Query(..., description="OAuth code returned by Strava"),
        scope: str | None = Query(default=None, description="Granted Strava scopes"),
    ) -> dict[str, object]:
        """Exchange the OAuth code, store credentials, and seed the local database.

        Parameters:
            code: OAuth code returned by Strava after user consent.
            scope: Optional scope string echoed back by Strava.

        Returns:
            dict[str, object]: Small JSON payload describing the connected athlete.

        Raises:
            HTTPException: Raised when Strava token exchange or profile fetch fails.
        """

        try:
            token_bundle = strava_client.exchange_code(code)
            repository.save_tokens(token_bundle)
            profile = strava_client.get_athlete(token_bundle.access_token)
            repository.save_athlete_profile(profile)
            if repository.is_empty():
                # Keep the first auth callback light enough for local development by
                # using the same bounded seed logic as the app lifespan hook.
                sync_service.run_startup_sync(initial_backfill_days)
            return {
                "status": "connected",
                "athlete_id": profile.athlete_id,
                "granted_scope": scope or token_bundle.scope,
            }
        except StravaClientError as error:
            LOGGER.exception("Strava OAuth callback failed")
            raise HTTPException(status_code=502, detail=str(error)) from error

    return router
