"""Health endpoint wiring."""

from __future__ import annotations

from fastapi import APIRouter

from strava_activity_sync.storage.repositories import StravaRepositoryProtocol


def build_health_router(repository: StravaRepositoryProtocol) -> APIRouter:
    """Build the health router for liveness and readiness checks.

    Parameters:
        repository: Repository used to inspect auth, activity, and sync state.

    Returns:
        APIRouter: Health router exposing a single lightweight JSON endpoint.
    """

    router = APIRouter(tags=["health"])

    @router.get("/health")
    def health() -> dict[str, object]:
        """Return a lightweight health payload.

        Returns:
            dict[str, object]: Basic health fields plus the most recent sync metadata.
        """

        reconciliation_state = repository.get_sync_state("reconciliation") or {}
        startup_state = repository.get_sync_state("startup_sync") or {}

        return {
            "status": "ok",
            "has_tokens": repository.get_tokens() is not None,
            "activity_count": len(repository.list_activities(include_deleted=True)),
            "last_sync_at": reconciliation_state.get("run_at"),
            "last_sync_phase": reconciliation_state.get("phase"),
            "last_sync_processed_count": reconciliation_state.get("processed_count"),
            "last_startup_sync_at": startup_state.get("run_at"),
        }

    return router
