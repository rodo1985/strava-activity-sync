"""Health endpoint wiring."""

from __future__ import annotations

from fastapi import APIRouter

from strava_activity_sync.storage.repositories import StravaRepository


def build_health_router(repository: StravaRepository) -> APIRouter:
    """Build the health router for liveness and readiness checks."""

    router = APIRouter(tags=["health"])

    @router.get("/health")
    def health() -> dict[str, object]:
        """Return a lightweight health payload."""

        return {
            "status": "ok",
            "has_tokens": repository.get_tokens() is not None,
            "activity_count": len(repository.list_activities(include_deleted=True)),
        }

    return router

