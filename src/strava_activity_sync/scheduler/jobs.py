"""Background scheduler wiring for reconciliation jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from strava_activity_sync.services.sync_service import SyncService


LOGGER = logging.getLogger(__name__)


class SchedulerService:
    """Owns the background reconciliation scheduler."""

    def __init__(self, sync_service: SyncService, interval_minutes: int, lookback_days: int) -> None:
        self.sync_service = sync_service
        self.interval_minutes = interval_minutes
        self.lookback_days = lookback_days
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        """Start the scheduler if it is not already running."""

        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self._run_reconciliation,
            "interval",
            minutes=self.interval_minutes,
            id="reconciliation",
            replace_existing=True,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        """Stop the scheduler if it is running."""

        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _run_reconciliation(self) -> None:
        """Run reconciliation in the background and log failures cleanly."""

        try:
            self.sync_service.reconcile(lookback_days=self.lookback_days)
        except Exception:  # pragma: no cover - APScheduler swallows job exceptions.
            LOGGER.exception("Scheduled reconciliation failed.")

