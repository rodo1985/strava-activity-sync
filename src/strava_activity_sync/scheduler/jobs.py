"""Background scheduler wiring for recent-first collection jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from strava_activity_sync.services.sync_service import SyncService


LOGGER = logging.getLogger(__name__)


class SchedulerService:
    """Own the background recent-first sync scheduler.

    Parameters:
        sync_service: Shared sync service used by scheduled jobs.
        interval_minutes: Frequency for scheduled collection runs.
        lookback_days: Recent window inspected before historical fallback begins.
    """

    def __init__(self, sync_service: SyncService, interval_minutes: int, lookback_days: int) -> None:
        self.sync_service = sync_service
        self.interval_minutes = interval_minutes
        self.lookback_days = lookback_days
        self.scheduler = BackgroundScheduler(
            timezone=timezone.utc,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )

    def start(self) -> None:
        """Start the scheduler if it is not already running.

        Returns:
            None: The scheduler starts in the current process when needed.
        """

        if self.scheduler.running:
            return
        next_run_time = datetime.now(timezone.utc) + timedelta(minutes=self.interval_minutes)
        self.scheduler.add_job(
            self._run_reconciliation,
            "interval",
            minutes=self.interval_minutes,
            id="reconciliation",
            replace_existing=True,
            next_run_time=next_run_time,
        )
        self.scheduler.start()
        LOGGER.info(
            "Scheduled recurring recent-first sync every %s minutes. Next run at %s.",
            self.interval_minutes,
            next_run_time.isoformat(),
        )

    def shutdown(self) -> None:
        """Stop the scheduler if it is running.

        Returns:
            None: The scheduler is stopped in place when active.
        """

        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _run_reconciliation(self) -> None:
        """Run the scheduled collection flow and log failures cleanly.

        Returns:
            None: Side effects are handled by the sync service and repository.
        """

        try:
            LOGGER.info(
                "Scheduled sync fired.",
                extra={"lookback_days": self.lookback_days, "interval_minutes": self.interval_minutes},
            )
            result = self.sync_service.reconcile(lookback_days=self.lookback_days)
            LOGGER.info(
                "Scheduled sync finished with %s processed activities.",
                len(result.processed_activity_ids),
            )
        except Exception:  # pragma: no cover - APScheduler swallows job exceptions.
            LOGGER.exception("Scheduled recent-first collection failed.")
