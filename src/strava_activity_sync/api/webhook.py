"""Strava webhook route wiring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from strava_activity_sync.services.strava_client import StravaClientError
from strava_activity_sync.services.sync_service import SyncService


LOGGER = logging.getLogger(__name__)


def build_webhook_router(sync_service: SyncService, verify_token: str) -> APIRouter:
    """Build Strava webhook verification and delivery routes."""

    router = APIRouter(tags=["webhooks"])

    @router.get("/webhooks/strava")
    def verify_webhook(
        hub_mode: str = Query(..., alias="hub.mode"),
        hub_challenge: str = Query(..., alias="hub.challenge"),
        hub_verify_token: str = Query(..., alias="hub.verify_token"),
    ) -> dict[str, str]:
        """Handle Strava webhook verification requests."""

        if hub_mode != "subscribe" or hub_verify_token != verify_token:
            raise HTTPException(status_code=403, detail="Invalid Strava webhook verification token.")
        return {"hub.challenge": hub_challenge}

    @router.post("/webhooks/strava")
    async def receive_webhook(request: Request) -> dict[str, object]:
        """Process Strava activity webhook events."""

        payload = await request.json()
        try:
            result = sync_service.handle_webhook_event(payload)
            return {
                "status": "accepted",
                "processed_activity_ids": result.processed_activity_ids if result else [],
            }
        except StravaClientError as error:
            LOGGER.exception("Strava webhook handling failed")
            raise HTTPException(status_code=502, detail=str(error)) from error

    return router

