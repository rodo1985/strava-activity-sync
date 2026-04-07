"""Vercel Blob-backed repository for serverless Strava deployments."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from vercel.blob import BlobClient

from strava_activity_sync.config import Settings
from strava_activity_sync.domain.models import (
    ActivityLap,
    ActivityRecord,
    ActivityStream,
    ActivityZone,
    AthleteProfile,
    OAuthTokenBundle,
)


def _default_state() -> dict[str, Any]:
    """Return the empty persisted state structure used by the blob backend.

    Returns:
        dict[str, Any]: Empty state payload for single-athlete storage.
    """

    return {
        "athlete_profile": None,
        "oauth_tokens": None,
        "activities": {},
        "sync_state": {},
        "webhook_events": [],
    }


class VercelBlobStravaRepository:
    """Repository that stores Strava state in a private Vercel Blob object.

    The backend intentionally trades some efficiency for deployment simplicity.
    A single JSON snapshot keeps the existing sync and render code largely
    unchanged while still providing durable serverless storage on Vercel.
    """

    def __init__(self, settings: Settings) -> None:
        """Create the blob-backed repository.

        Parameters:
            settings: Application settings providing blob storage paths and
                access mode.
        """

        self.settings = settings
        self.client = BlobClient()

    def save_athlete_profile(self, profile: AthleteProfile) -> None:
        """Persist the single-athlete profile in blob state."""

        state = self._load_state()
        state["athlete_profile"] = {
            "athlete_id": profile.athlete_id,
            "username": profile.username,
            "firstname": profile.firstname,
            "lastname": profile.lastname,
            "raw_payload": profile.raw_payload,
        }
        self._save_state(state)

    def get_athlete_profile(self) -> AthleteProfile | None:
        """Return the stored athlete profile when available."""

        payload = self._load_state()["athlete_profile"]
        if payload is None:
            return None
        return AthleteProfile(
            athlete_id=int(payload["athlete_id"]),
            username=payload.get("username"),
            firstname=payload.get("firstname"),
            lastname=payload.get("lastname"),
            raw_payload=payload.get("raw_payload", {}),
        )

    def save_tokens(self, tokens: OAuthTokenBundle) -> None:
        """Persist the latest OAuth token bundle in blob state."""

        state = self._load_state()
        state["oauth_tokens"] = {
            "athlete_id": tokens.athlete_id,
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
            "scope": tokens.scope,
            "raw_payload": tokens.raw_payload,
        }
        self._save_state(state)

    def get_tokens(self) -> OAuthTokenBundle | None:
        """Return the stored OAuth token bundle when available."""

        payload = self._load_state()["oauth_tokens"]
        if payload is None:
            return None
        return OAuthTokenBundle(
            athlete_id=int(payload["athlete_id"]),
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            expires_at=int(payload["expires_at"]),
            scope=payload["scope"],
            raw_payload=payload.get("raw_payload", {}),
        )

    def upsert_activity_bundle(self, activity: ActivityRecord) -> None:
        """Persist a full activity bundle inside the blob state snapshot."""

        state = self._load_state()
        state["activities"][str(activity.activity_id)] = self._serialize_activity(activity)
        self._save_state(state)

    def mark_activity_deleted(self, activity_id: int) -> None:
        """Tombstone an activity while preserving its stored detail."""

        state = self._load_state()
        payload = state["activities"].get(str(activity_id))
        if payload is None:
            return
        payload["deleted"] = True
        state["activities"][str(activity_id)] = payload
        self._save_state(state)

    def is_empty(self) -> bool:
        """Return whether any activities are stored in blob state."""

        return len(self._load_state()["activities"]) == 0

    def list_activities(self, include_deleted: bool = False) -> list[ActivityRecord]:
        """Return stored activities from the blob state snapshot."""

        payloads = self._load_state()["activities"].values()
        activities = [self._deserialize_activity(payload) for payload in payloads]
        if not include_deleted:
            activities = [activity for activity in activities if not activity.deleted]
        return sorted(activities, key=lambda item: item.start_date, reverse=True)

    def get_latest_activity_start_date(self) -> datetime | None:
        """Return the newest stored activity start time, if any."""

        activities = self.list_activities()
        if not activities:
            return None
        return activities[0].start_date

    def set_sync_state(self, key: str, value: dict[str, Any]) -> None:
        """Persist a JSON sync-state payload inside blob state."""

        state = self._load_state()
        state["sync_state"][key] = value
        self._save_state(state)

    def get_sync_state(self, key: str) -> dict[str, Any] | None:
        """Return a JSON sync-state payload by key."""

        return self._load_state()["sync_state"].get(key)

    def record_webhook_event(self, payload: dict[str, Any], outcome: str) -> None:
        """Append a webhook audit record to the blob state snapshot."""

        state = self._load_state()
        state["webhook_events"].append(
            {
                "payload": payload,
                "outcome": outcome,
                "processed_at": datetime.utcnow().isoformat() + "Z",
            }
        )
        # Keep only the latest 200 webhook events to avoid unbounded growth in
        # the state snapshot while still preserving recent debugging history.
        state["webhook_events"] = state["webhook_events"][-200:]
        self._save_state(state)

    def activity_exists(self, activity_id: int) -> bool:
        """Return whether an activity already exists in blob state."""

        return str(activity_id) in self._load_state()["activities"]

    def get_oldest_activity_start_date(self) -> datetime | None:
        """Return the oldest stored non-deleted activity start time."""

        activities = self.list_activities()
        if not activities:
            return None
        return activities[-1].start_date

    def _load_state(self) -> dict[str, Any]:
        """Load and decode the persisted state snapshot from Vercel Blob.

        Returns:
            dict[str, Any]: Decoded repository state, or a new empty snapshot
                when no state blob has been written yet.
        """

        result = self.client.get(
            self.settings.vercel_blob_state_path,
            access=self.settings.vercel_blob_access,
        )
        if result is None or result.status_code != 200:
            return _default_state()
        return json.loads(result.content.decode("utf-8"))

    def _save_state(self, state: dict[str, Any]) -> None:
        """Persist the full repository state snapshot to Vercel Blob.

        Parameters:
            state: Fully serialized repository state that should overwrite the
                previously stored snapshot.
        """

        self.client.put(
            self.settings.vercel_blob_state_path,
            json.dumps(state, indent=2, sort_keys=True).encode("utf-8"),
            access=self.settings.vercel_blob_access,
            content_type="application/json",
            overwrite=True,
        )

    def _serialize_activity(self, activity: ActivityRecord) -> dict[str, Any]:
        """Convert an activity record into JSON-safe blob state."""

        return {
            "activity_id": activity.activity_id,
            "athlete_id": activity.athlete_id,
            "name": activity.name,
            "sport_type": activity.sport_type,
            "start_date": activity.start_date.isoformat(),
            "timezone": activity.timezone,
            "distance_meters": activity.distance_meters,
            "moving_time_seconds": activity.moving_time_seconds,
            "elapsed_time_seconds": activity.elapsed_time_seconds,
            "total_elevation_gain_meters": activity.total_elevation_gain_meters,
            "average_speed_mps": activity.average_speed_mps,
            "max_speed_mps": activity.max_speed_mps,
            "average_heartrate": activity.average_heartrate,
            "max_heartrate": activity.max_heartrate,
            "average_watts": activity.average_watts,
            "weighted_average_watts": activity.weighted_average_watts,
            "kilojoules": activity.kilojoules,
            "suffer_score": activity.suffer_score,
            "trainer": activity.trainer,
            "commute": activity.commute,
            "manual": activity.manual,
            "is_private": activity.is_private,
            "deleted": activity.deleted,
            "raw_payload": activity.raw_payload,
            "zones": [self._serialize_zone(zone) for zone in activity.zones],
            "laps": [self._serialize_lap(lap) for lap in activity.laps],
            "streams": {
                key: self._serialize_stream(stream) for key, stream in activity.streams.items()
            },
        }

    def _deserialize_activity(self, payload: dict[str, Any]) -> ActivityRecord:
        """Convert JSON state back into a full activity record."""

        return ActivityRecord(
            activity_id=int(payload["activity_id"]),
            athlete_id=int(payload["athlete_id"]),
            name=payload["name"],
            sport_type=payload["sport_type"],
            start_date=datetime.fromisoformat(payload["start_date"]),
            timezone=payload.get("timezone"),
            distance_meters=float(payload["distance_meters"]),
            moving_time_seconds=int(payload["moving_time_seconds"]),
            elapsed_time_seconds=int(payload["elapsed_time_seconds"]),
            total_elevation_gain_meters=payload.get("total_elevation_gain_meters"),
            average_speed_mps=payload.get("average_speed_mps"),
            max_speed_mps=payload.get("max_speed_mps"),
            average_heartrate=payload.get("average_heartrate"),
            max_heartrate=payload.get("max_heartrate"),
            average_watts=payload.get("average_watts"),
            weighted_average_watts=payload.get("weighted_average_watts"),
            kilojoules=payload.get("kilojoules"),
            suffer_score=payload.get("suffer_score"),
            trainer=bool(payload.get("trainer", False)),
            commute=bool(payload.get("commute", False)),
            manual=bool(payload.get("manual", False)),
            is_private=bool(payload.get("is_private", False)),
            deleted=bool(payload.get("deleted", False)),
            raw_payload=payload.get("raw_payload", {}),
            zones=[self._deserialize_zone(zone) for zone in payload.get("zones", [])],
            laps=[self._deserialize_lap(lap) for lap in payload.get("laps", [])],
            streams={
                key: self._deserialize_stream(stream)
                for key, stream in payload.get("streams", {}).items()
            },
        )

    def _serialize_zone(self, zone: ActivityZone) -> dict[str, Any]:
        """Convert one zone row into JSON-safe state."""

        return {
            "activity_id": zone.activity_id,
            "resource": zone.resource,
            "zone_index": zone.zone_index,
            "min_value": zone.min_value,
            "max_value": zone.max_value,
            "time_seconds": zone.time_seconds,
            "raw_payload": zone.raw_payload,
        }

    def _deserialize_zone(self, payload: dict[str, Any]) -> ActivityZone:
        """Convert JSON state into one activity zone row."""

        return ActivityZone(
            activity_id=int(payload["activity_id"]),
            resource=payload["resource"],
            zone_index=int(payload["zone_index"]),
            min_value=payload.get("min_value"),
            max_value=payload.get("max_value"),
            time_seconds=int(payload["time_seconds"]),
            raw_payload=payload.get("raw_payload", {}),
        )

    def _serialize_lap(self, lap: ActivityLap) -> dict[str, Any]:
        """Convert one lap row into JSON-safe state."""

        return {
            "lap_id": lap.lap_id,
            "activity_id": lap.activity_id,
            "lap_index": lap.lap_index,
            "name": lap.name,
            "elapsed_time_seconds": lap.elapsed_time_seconds,
            "moving_time_seconds": lap.moving_time_seconds,
            "distance_meters": lap.distance_meters,
            "average_speed_mps": lap.average_speed_mps,
            "average_heartrate": lap.average_heartrate,
            "max_heartrate": lap.max_heartrate,
            "average_watts": lap.average_watts,
            "pace_zone": lap.pace_zone,
            "split": lap.split,
            "raw_payload": lap.raw_payload,
        }

    def _deserialize_lap(self, payload: dict[str, Any]) -> ActivityLap:
        """Convert JSON state into one lap row."""

        return ActivityLap(
            lap_id=int(payload["lap_id"]),
            activity_id=int(payload["activity_id"]),
            lap_index=int(payload["lap_index"]),
            name=payload.get("name"),
            elapsed_time_seconds=int(payload["elapsed_time_seconds"]),
            moving_time_seconds=int(payload["moving_time_seconds"]),
            distance_meters=float(payload["distance_meters"]),
            average_speed_mps=payload.get("average_speed_mps"),
            average_heartrate=payload.get("average_heartrate"),
            max_heartrate=payload.get("max_heartrate"),
            average_watts=payload.get("average_watts"),
            pace_zone=payload.get("pace_zone"),
            split=payload.get("split"),
            raw_payload=payload.get("raw_payload", {}),
        )

    def _serialize_stream(self, stream: ActivityStream) -> dict[str, Any]:
        """Convert one activity stream into JSON-safe state."""

        return {
            "activity_id": stream.activity_id,
            "stream_key": stream.stream_key,
            "data": stream.data,
            "series_type": stream.series_type,
            "original_size": stream.original_size,
            "resolution": stream.resolution,
            "raw_payload": stream.raw_payload,
        }

    def _deserialize_stream(self, payload: dict[str, Any]) -> ActivityStream:
        """Convert JSON state into one activity stream."""

        return ActivityStream(
            activity_id=int(payload["activity_id"]),
            stream_key=payload["stream_key"],
            data=payload.get("data", []),
            series_type=payload.get("series_type"),
            original_size=payload.get("original_size"),
            resolution=payload.get("resolution"),
            raw_payload=payload.get("raw_payload", {}),
        )
