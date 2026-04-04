"""Backfill helpers built on top of the sync service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strava_activity_sync.services.sync_service import SyncResult, SyncService


class BackfillService:
    """Service responsible for explicit historical backfills.

    Parameters:
        sync_service: Shared sync service used to fetch and persist activities.
    """

    def __init__(self, sync_service: SyncService) -> None:
        self.sync_service = sync_service

    def backfill_days(self, days: int) -> SyncResult:
        """Backfill the requested trailing window using a bounded batch.

        Parameters:
            days: Number of trailing days that define the manual backfill window.

        Returns:
            SyncResult: Sync summary for the batch of activities fetched.

        Notes:
            Manual backfills deliberately skip activity streams so repeated runs can
            grow older history without exhausting Strava's stricter read limits.
        """

        after = datetime.now(timezone.utc) - timedelta(days=days)
        result = self.sync_service.sync_range(
            after=after,
            max_activities=self.sync_service.sync_batch_size,
            include_streams=False,
            only_unknown=True,
        )
        self.sync_service.repository.set_sync_state(
            "manual_backfill",
            {
                "days": days,
                "run_at": datetime.now(timezone.utc).isoformat(),
                "batch_size": self.sync_service.sync_batch_size,
                "include_streams": False,
                "processed_count": len(result.processed_activity_ids),
            },
        )
        return result
