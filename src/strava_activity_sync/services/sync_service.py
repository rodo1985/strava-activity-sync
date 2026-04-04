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
from strava_activity_sync.services.render_service import RenderService
from strava_activity_sync.services.strava_client import StravaClient, StravaClientError
from strava_activity_sync.storage.repositories import StravaRepository


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncResult:
    """Result returned by sync operations."""

    processed_activity_ids: list[int]
    exported_paths: list[str]


class SyncService:
    """Orchestrates Strava API access, SQLite persistence, and deterministic renders."""

    def __init__(
        self,
        repository: StravaRepository,
        strava_client: StravaClient,
        render_service: RenderService,
    ) -> None:
        self.repository = repository
        self.strava_client = strava_client
        self.render_service = render_service

    def sync_activity(self, activity_id: int) -> SyncResult:
        """Fetch and upsert a single activity, then re-render outputs."""

        token_bundle = self._get_valid_tokens()
        detail = self.strava_client.get_activity(token_bundle.access_token, activity_id)
        zones = self.strava_client.get_activity_zones(token_bundle.access_token, activity_id)
        laps = self.strava_client.get_activity_laps(token_bundle.access_token, activity_id)
        streams = self.strava_client.get_activity_streams(token_bundle.access_token, activity_id)

        activity = build_activity_record(detail, zones, laps, streams)
        self.repository.upsert_activity_bundle(activity)
        exported_paths = [str(path) for path in self.render_service.render_and_export(self.repository.list_activities())]
        return SyncResult(processed_activity_ids=[activity_id], exported_paths=exported_paths)

    def sync_range(
        self,
        *,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> SyncResult:
        """Fetch and upsert activities in a time window, then render outputs once."""

        token_bundle = self._get_valid_tokens()
        processed: list[int] = []
        for activity_stub in self.strava_client.iter_activities(
            token_bundle.access_token,
            after=after,
            before=before,
        ):
            activity_id = int(activity_stub["id"])
            processed.append(activity_id)
            detail = self.strava_client.get_activity(token_bundle.access_token, activity_id)
            zones = self.strava_client.get_activity_zones(token_bundle.access_token, activity_id)
            laps = self.strava_client.get_activity_laps(token_bundle.access_token, activity_id)
            streams = self.strava_client.get_activity_streams(token_bundle.access_token, activity_id)
            activity = build_activity_record(detail, zones, laps, streams)
            self.repository.upsert_activity_bundle(activity)

        exported_paths = [str(path) for path in self.render_service.render_and_export(self.repository.list_activities())]
        return SyncResult(processed_activity_ids=processed, exported_paths=exported_paths)

    def reconcile(self, lookback_days: int = 7) -> SyncResult:
        """Reconcile recent activities using an overlap-safe lookback window."""

        latest_start = self.repository.get_latest_activity_start_date()
        overlap_start = latest_start - timedelta(days=2) if latest_start else None
        requested_start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        after = max_datetime(overlap_start, requested_start)
        result = self.sync_range(after=after)
        self.repository.set_sync_state(
            "reconciliation",
            {
                "lookback_days": lookback_days,
                "run_at": datetime.now(timezone.utc).isoformat(),
                "processed_count": len(result.processed_activity_ids),
            },
        )
        return result

    def render_exports(self) -> list[str]:
        """Render exports from the current database contents without calling Strava."""

        return [str(path) for path in self.render_service.render_and_export(self.repository.list_activities())]

    def maybe_run_initial_backfill(self, days: int) -> SyncResult | None:
        """Run the first startup backfill when the database is empty and auth exists."""

        if not self.repository.is_empty():
            return None
        if self.repository.get_tokens() is None:
            LOGGER.info("Skipping initial backfill because no Strava tokens are stored yet.")
            return None

        after = datetime.now(timezone.utc) - timedelta(days=days)
        result = self.sync_range(after=after)
        self.repository.set_sync_state(
            "initial_backfill",
            {
                "days": days,
                "run_at": datetime.now(timezone.utc).isoformat(),
                "processed_count": len(result.processed_activity_ids),
            },
        )
        return result

    def handle_webhook_event(self, payload: dict[str, Any]) -> SyncResult | None:
        """Handle a Strava webhook event and keep renders in sync."""

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
            exported_paths = [str(path) for path in self.render_service.render_and_export(self.repository.list_activities())]
            self.repository.record_webhook_event(payload, "deleted")
            return SyncResult(processed_activity_ids=[event.object_id], exported_paths=exported_paths)

        result = self.sync_activity(event.object_id)
        self.repository.record_webhook_event(payload, event.aspect_type)
        return result

    def _get_valid_tokens(self) -> OAuthTokenBundle:
        """Return a valid token bundle, refreshing it if needed."""

        token_bundle = self.repository.get_tokens()
        if token_bundle is None:
            raise StravaClientError("No OAuth tokens are stored. Complete the Strava OAuth flow first.")

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if token_bundle.expires_at > now_ts + 120:
            return token_bundle

        refreshed = self.strava_client.refresh_token(token_bundle.refresh_token)
        self.repository.save_tokens(refreshed)
        return refreshed


def max_datetime(left: datetime | None, right: datetime | None) -> datetime | None:
    """Return the later of two datetimes while tolerating missing values."""

    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


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
