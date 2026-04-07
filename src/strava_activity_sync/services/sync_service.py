"""Core synchronization logic for webhook-driven and scheduled Strava ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from strava_activity_sync.domain.models import (
    ActivityEvent,
    ActivityLap,
    ActivityRecord,
    ActivityStream,
    ActivityZone,
    OAuthTokenBundle,
)
from strava_activity_sync.services.apex_supabase_projector import ApexSupabaseProjector
from strava_activity_sync.services.render_service import RenderService
from strava_activity_sync.services.strava_client import StravaClient, StravaClientError
from strava_activity_sync.storage.repositories import StravaRepositoryProtocol


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncResult:
    """Result returned by sync operations.

    Attributes:
        processed_activity_ids: Activity identifiers that were newly fetched or updated.
        exported_paths: Artifact paths written by the render service for this sync run.
    """

    processed_activity_ids: list[int]
    exported_paths: list[str]


class SyncService:
    """Orchestrate Strava API access, SQLite persistence, and deterministic renders.

    Parameters:
        repository: Repository used for SQLite reads and writes.
        strava_client: HTTP client wrapper for Strava endpoints.
        render_service: Deterministic renderer for Markdown and JSON exports.
        sync_batch_size: Default cap for batched sync operations.
        apex_projector: Optional APEX Supabase projector used to mirror synced
            activities into the user's existing daily-log schema.

    Example:
        >>> service = SyncService(repository, client, render_service, sync_batch_size=32)
        >>> service.render_exports()
        ['/tmp/exports/dashboard.md']
    """

    def __init__(
        self,
        repository: StravaRepositoryProtocol,
        strava_client: StravaClient,
        render_service: RenderService,
        sync_batch_size: int = 32,
        apex_projector: ApexSupabaseProjector | None = None,
    ) -> None:
        self.repository = repository
        self.strava_client = strava_client
        self.render_service = render_service
        self.sync_batch_size = max(1, sync_batch_size)
        self.apex_projector = apex_projector

    def sync_activity(
        self,
        activity_id: int,
        *,
        include_streams: bool = True,
        render_after: bool = True,
        token_bundle: OAuthTokenBundle | None = None,
    ) -> SyncResult:
        """Fetch and upsert a single activity, then optionally re-render outputs.

        Parameters:
            activity_id: Strava activity identifier to fetch.
            include_streams: When `True`, fetch full stream data for deeper analysis.
            render_after: When `True`, regenerate exports after the upsert.
            token_bundle: Optional prevalidated OAuth bundle reused within a batch.

        Returns:
            SyncResult: Sync summary containing the processed activity and exported paths.

        Raises:
            StravaClientError: Propagates token and Strava API failures.
        """

        resolved_tokens = token_bundle or self._get_valid_tokens()
        self._sync_activity_bundle(
            activity_id=activity_id,
            token_bundle=resolved_tokens,
            include_streams=include_streams,
        )
        exported_paths = self._render_if_needed(render_after=render_after, processed_count=1)
        return SyncResult(processed_activity_ids=[activity_id], exported_paths=exported_paths)

    def sync_range(
        self,
        *,
        after: datetime | None = None,
        before: datetime | None = None,
        max_activities: int | None = None,
        include_streams: bool = False,
        only_unknown: bool = True,
        max_pages: int | None = None,
    ) -> SyncResult:
        """Fetch and upsert activities in a time window, then render outputs once.

        Parameters:
            after: Optional inclusive lower time bound.
            before: Optional exclusive upper time bound.
            max_activities: Maximum number of unknown activities to hydrate this run.
            include_streams: When `True`, fetch activity streams in addition to summary detail.
            only_unknown: When `True`, skip activity identifiers already stored locally.
            max_pages: Optional cap on Strava summary pages inspected for this run.

        Returns:
            SyncResult: Sync summary for newly ingested activities.

        Raises:
            StravaClientError: Propagates token and Strava API failures.
        """

        token_bundle = self._get_valid_tokens()
        resolved_max = self._resolve_batch_size(max_activities)
        processed: list[int] = []

        for activity_stub in self.strava_client.iter_activities(
            token_bundle.access_token,
            after=after,
            before=before,
            per_page=resolved_max,
            max_pages=max_pages,
        ):
            activity_id = int(activity_stub["id"])
            if only_unknown and self.repository.activity_exists(activity_id):
                continue

            self._sync_activity_bundle(
                activity_id=activity_id,
                token_bundle=token_bundle,
                include_streams=include_streams,
            )
            processed.append(activity_id)
            if len(processed) >= resolved_max:
                break

        exported_paths = self._render_if_needed(render_after=True, processed_count=len(processed))
        return SyncResult(processed_activity_ids=processed, exported_paths=exported_paths)

    def sync_recent_window(
        self,
        lookback_days: int = 14,
        *,
        max_activities: int | None = None,
        include_streams: bool = False,
    ) -> SyncResult:
        """Sync the newest activity summaries inside the recent lookback window.

        Parameters:
            lookback_days: Number of trailing days to consider recent.
            max_activities: Maximum number of unknown activities to fetch this run.
            include_streams: When `True`, fetch streams during the recent sync.

        Returns:
            SyncResult: Sync summary for newly ingested recent activities.

        Notes:
            Recent-window sync is capped to the first summary page on purpose so the
            scheduler only inspects the newest activity stubs each cycle.
        """

        after = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        return self.sync_range(
            after=after,
            max_activities=max_activities,
            include_streams=include_streams,
            only_unknown=True,
            max_pages=1,
        )

    def sync_historical_window(
        self,
        *,
        max_activities: int | None = None,
        include_streams: bool = False,
    ) -> SyncResult:
        """Sync one older summary page before the oldest stored activity.

        Parameters:
            max_activities: Maximum number of unknown historical activities to fetch.
            include_streams: When `True`, fetch streams during the historical sync.

        Returns:
            SyncResult: Sync summary for newly ingested historical activities.
        """

        oldest_start = self.repository.get_oldest_activity_start_date()
        if oldest_start is None:
            return SyncResult(processed_activity_ids=[], exported_paths=[])

        return self.sync_range(
            before=oldest_start,
            max_activities=max_activities,
            include_streams=include_streams,
            only_unknown=True,
            max_pages=1,
        )

    def reconcile(self, lookback_days: int = 7) -> SyncResult:
        """Run the rate-safe scheduled collector used for local-first sync.

        Parameters:
            lookback_days: Number of trailing days to inspect for recent activities.

        Returns:
            SyncResult: Sync summary for the recent pass or historical fallback.

        Notes:
            The collector first inspects the newest recent summaries. If no new
            activities are found there, it spends the cycle on a small historical
            backfill page so older history grows over time without a large burst.
        """

        return self.run_recent_first_cycle(
            lookback_days=lookback_days,
            trigger="scheduled",
        )

    def run_startup_sync(self, lookback_days: int) -> SyncResult | None:
        """Run the startup sync that executes whenever the application boots.

        Parameters:
            lookback_days: Number of trailing days to inspect during startup.

        Returns:
            SyncResult | None: Sync summary when tokens are available, otherwise `None`.

        Notes:
            Startup sync always checks for recent unknown activities immediately so a
            local process restart does not have to wait for the next 16-minute interval.
        """

        if self.repository.get_tokens() is None:
            LOGGER.info("Skipping startup sync because no Strava tokens are stored yet.")
            return None

        return self.run_recent_first_cycle(
            lookback_days=lookback_days,
            trigger="startup",
        )

    def run_recent_first_cycle(self, *, lookback_days: int, trigger: str) -> SyncResult:
        """Run one recent-first sync cycle and persist traceable sync metadata.

        Parameters:
            lookback_days: Number of trailing days to inspect for recent activities.
            trigger: Short label describing why the cycle is running.

        Returns:
            SyncResult: Sync summary for the recent pass or historical fallback.
        """

        LOGGER.info(
            "Starting %s sync cycle.",
            trigger,
            extra={"lookback_days": lookback_days, "batch_size": self.sync_batch_size},
        )

        result = self.sync_recent_window(
            lookback_days=lookback_days,
            max_activities=self.sync_batch_size,
            include_streams=False,
        )
        phase = "recent"
        if not result.processed_activity_ids:
            # Historical backfill intentionally skips streams so a 15-16 minute
            # scheduler cadence stays under Strava's tighter read limits.
            result = self.sync_historical_window(
                max_activities=self.sync_batch_size,
                include_streams=False,
            )
            phase = "historical" if result.processed_activity_ids else "idle"

        state_payload = {
            "trigger": trigger,
            "lookback_days": lookback_days,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "batch_size": self.sync_batch_size,
            "processed_count": len(result.processed_activity_ids),
            "processed_activity_ids": result.processed_activity_ids,
        }
        self.repository.set_sync_state("reconciliation", state_payload)
        if trigger == "startup":
            self.repository.set_sync_state("startup_sync", state_payload)

        LOGGER.info(
            "Completed %s sync cycle.",
            trigger,
            extra={
                "phase": phase,
                "processed_count": len(result.processed_activity_ids),
                "processed_activity_ids": result.processed_activity_ids,
            },
        )
        return result

    def render_exports(self) -> list[str]:
        """Render exports from the current database contents without calling Strava.

        Returns:
            list[str]: File paths written by the render service.
        """

        return [str(path) for path in self.render_service.render_and_export(self.repository.list_activities())]

    def maybe_run_initial_backfill(self, days: int) -> SyncResult | None:
        """Run the first startup sync when the database is empty and auth exists.

        Parameters:
            days: Trailing-window size used to seed the local mirror.

        Returns:
            SyncResult | None: The sync summary when startup work ran, otherwise `None`.

        Notes:
            Startup seeding is intentionally bounded to the configured batch size and
            skips streams so the first auth flow does not immediately exhaust rate
            limits on modest Strava accounts.
        """

        if not self.repository.is_empty():
            return None
        if self.repository.get_tokens() is None:
            LOGGER.info("Skipping initial backfill because no Strava tokens are stored yet.")
            return None

        after = datetime.now(timezone.utc) - timedelta(days=days)
        result = self.sync_range(
            after=after,
            max_activities=self.sync_batch_size,
            include_streams=False,
            only_unknown=True,
        )
        self.repository.set_sync_state(
            "initial_backfill",
            {
                "days": days,
                "run_at": datetime.now(timezone.utc).isoformat(),
                "batch_size": self.sync_batch_size,
                "include_streams": False,
                "processed_count": len(result.processed_activity_ids),
            },
        )
        return result

    def handle_webhook_event(self, payload: dict[str, Any]) -> SyncResult | None:
        """Handle a Strava webhook event and keep renders in sync.

        Parameters:
            payload: Raw webhook payload delivered by Strava.

        Returns:
            SyncResult | None: A sync summary for activity events, or `None` when ignored.
        """

        event = ActivityEvent(
            aspect_type=payload["aspect_type"],
            object_id=int(payload["object_id"]),
            object_type=payload["object_type"],
            owner_id=int(payload["owner_id"]),
            event_time=int(payload["event_time"]),
            updates=payload.get("updates", {}),
            raw_payload=payload,
        )
        if event.object_type != "activity":
            self.repository.record_webhook_event(payload, "ignored_non_activity")
            return None

        if event.aspect_type == "delete":
            self.repository.mark_activity_deleted(event.object_id)
            if self.apex_projector is not None:
                self.apex_projector.delete_activity(event.object_id)
            exported_paths = self._render_if_needed(render_after=True, processed_count=1)
            self.repository.record_webhook_event(payload, "deleted")
            return SyncResult(processed_activity_ids=[event.object_id], exported_paths=exported_paths)

        result = self.sync_activity(event.object_id)
        self.repository.record_webhook_event(payload, event.aspect_type)
        return result

    def _resolve_batch_size(self, requested_size: int | None) -> int:
        """Resolve a caller-provided batch size against the service default.

        Parameters:
            requested_size: Optional override for the batch size.

        Returns:
            int: A positive batch size used for the current sync run.
        """

        if requested_size is None:
            return self.sync_batch_size
        return max(1, requested_size)

    def _sync_activity_bundle(
        self,
        *,
        activity_id: int,
        token_bundle: OAuthTokenBundle,
        include_streams: bool,
    ) -> None:
        """Fetch all configured Strava payloads for one activity and persist them.

        Parameters:
            activity_id: Strava activity identifier to hydrate.
            token_bundle: Valid OAuth token bundle reused within the batch.
            include_streams: Whether stream payloads should be fetched.

        Returns:
            None: The activity bundle is stored in SQLite in place.

        Raises:
            StravaClientError: Propagates Strava API failures from detail endpoints.
        """

        detail = self.strava_client.get_activity(token_bundle.access_token, activity_id)
        zones = self.strava_client.get_activity_zones(token_bundle.access_token, activity_id)
        laps = self.strava_client.get_activity_laps(token_bundle.access_token, activity_id)
        streams = (
            self.strava_client.get_activity_streams(token_bundle.access_token, activity_id)
            if include_streams
            else {}
        )
        activity = build_activity_record(detail, zones, laps, streams)
        self.repository.upsert_activity_bundle(activity)
        if self.apex_projector is not None:
            self.apex_projector.project_activity(activity)

    def _render_if_needed(self, *, render_after: bool, processed_count: int) -> list[str]:
        """Render exports only when the caller requested it and data changed.

        Parameters:
            render_after: Whether the current sync flow wants rendered outputs.
            processed_count: Number of activities written during the sync flow.

        Returns:
            list[str]: Exported file paths or an empty list when rendering was skipped.
        """

        if not render_after or processed_count == 0:
            return []
        return [str(path) for path in self.render_service.render_and_export(self.repository.list_activities())]

    def _get_valid_tokens(self) -> OAuthTokenBundle:
        """Return a valid token bundle, refreshing it if needed.

        Returns:
            OAuthTokenBundle: Token bundle that is safe to use for the current request.

        Raises:
            StravaClientError: Raised when no tokens are stored yet.
        """

        token_bundle = self.repository.get_tokens()
        if token_bundle is None:
            raise StravaClientError("No OAuth tokens are stored. Complete the Strava OAuth flow first.")

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if token_bundle.expires_at > now_ts + 120:
            return token_bundle

        refreshed = self.strava_client.refresh_token(
            token_bundle.refresh_token,
            athlete_id=token_bundle.athlete_id,
        )
        self.repository.save_tokens(refreshed)
        return refreshed

def build_activity_record(
    detail: dict[str, Any],
    zones_payload: list[dict[str, Any]],
    laps_payload: list[dict[str, Any]],
    streams_payload: dict[str, Any],
) -> ActivityRecord:
    """Convert raw Strava payloads into the normalized activity bundle."""

    activity_id = int(detail["id"])
    athlete_id = int(detail["athlete"]["id"])
    activity = ActivityRecord(
        activity_id=activity_id,
        athlete_id=athlete_id,
        name=detail.get("name", f"Activity {activity_id}"),
        sport_type=detail.get("sport_type") or detail.get("type", "Unknown"),
        start_date=datetime.fromisoformat(detail["start_date"].replace("Z", "+00:00")),
        timezone=detail.get("timezone"),
        distance_meters=float(detail.get("distance", 0.0)),
        moving_time_seconds=int(detail.get("moving_time", 0)),
        elapsed_time_seconds=int(detail.get("elapsed_time", 0)),
        total_elevation_gain_meters=detail.get("total_elevation_gain"),
        average_speed_mps=detail.get("average_speed"),
        max_speed_mps=detail.get("max_speed"),
        average_heartrate=detail.get("average_heartrate"),
        max_heartrate=detail.get("max_heartrate"),
        average_watts=detail.get("average_watts"),
        weighted_average_watts=detail.get("weighted_average_watts"),
        kilojoules=detail.get("kilojoules"),
        suffer_score=detail.get("suffer_score"),
        trainer=bool(detail.get("trainer", False)),
        commute=bool(detail.get("commute", False)),
        manual=bool(detail.get("manual", False)),
        is_private=bool(detail.get("private", False)),
        deleted=False,
        raw_payload=detail,
    )
    activity.zones = build_zones(activity_id, zones_payload)
    activity.laps = build_laps(activity_id, laps_payload)
    activity.streams = build_streams(activity_id, streams_payload)
    return activity


def build_zones(activity_id: int, zones_payload: list[dict[str, Any]]) -> list[ActivityZone]:
    """Convert Strava zone payloads into normalized zone rows."""

    zones: list[ActivityZone] = []
    for resource_payload in zones_payload:
        resource = resource_payload.get("type", "unknown")
        for zone_index, zone_payload in enumerate(resource_payload.get("distribution_buckets", [])):
            zones.append(
                ActivityZone(
                    activity_id=activity_id,
                    resource=resource,
                    zone_index=zone_index,
                    min_value=zone_payload.get("min"),
                    max_value=zone_payload.get("max"),
                    time_seconds=int(zone_payload.get("time", 0)),
                    raw_payload=zone_payload,
                )
            )
    return zones


def build_laps(activity_id: int, laps_payload: list[dict[str, Any]]) -> list[ActivityLap]:
    """Convert Strava lap payloads into normalized lap rows."""

    laps: list[ActivityLap] = []
    for lap_index, lap_payload in enumerate(laps_payload, start=1):
        # Use an activity-scoped synthetic identifier so fixtures or third-party
        # tools that reuse lap IDs across activities do not violate SQLite's
        # primary key constraint.
        lap_id = int(f"{activity_id}{lap_index:03d}")
        laps.append(
            ActivityLap(
                lap_id=lap_id,
                activity_id=activity_id,
                lap_index=lap_index,
                name=lap_payload.get("name"),
                elapsed_time_seconds=int(lap_payload.get("elapsed_time", 0)),
                moving_time_seconds=int(lap_payload.get("moving_time", 0)),
                distance_meters=float(lap_payload.get("distance", 0.0)),
                average_speed_mps=lap_payload.get("average_speed"),
                average_heartrate=lap_payload.get("average_heartrate"),
                max_heartrate=lap_payload.get("max_heartrate"),
                average_watts=lap_payload.get("average_watts"),
                pace_zone=lap_payload.get("pace_zone"),
                split=lap_payload.get("split"),
                raw_payload=lap_payload,
            )
        )
    return laps


def build_streams(activity_id: int, streams_payload: dict[str, Any]) -> dict[str, ActivityStream]:
    """Convert Strava streams keyed by type into normalized stream rows."""

    streams: dict[str, ActivityStream] = {}
    for key, payload in streams_payload.items():
        streams[key] = ActivityStream(
            activity_id=activity_id,
            stream_key=key,
            data=payload.get("data", []),
            series_type=payload.get("series_type"),
            original_size=payload.get("original_size"),
            resolution=payload.get("resolution"),
            raw_payload=payload,
        )
    return streams
