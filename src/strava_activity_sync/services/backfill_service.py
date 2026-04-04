"""Backfill helpers built on top of the sync service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strava_activity_sync.services.sync_service import SyncResult, SyncService


class BackfillService:
    """Service responsible for explicit historical backfills."""

    def __init__(self, sync_service: SyncService) -> None:
        self.sync_service = sync_service

    def backfill_days(self, days: int) -> SyncResult:
        """Backfill the requested number of days of Strava activities."""

        after = datetime.now(timezone.utc) - timedelta(days=days)
        return self.sync_service.sync_range(after=after)
