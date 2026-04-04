"""Repository layer for persisting Strava data in SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from strava_activity_sync.domain.models import (
    ActivityLap,
    ActivityRecord,
    ActivityStream,
    ActivityZone,
    AthleteProfile,
    OAuthTokenBundle,
)
from strava_activity_sync.storage.db import Database


class StravaRepository:
    """Repository responsible for tokens, activities, and sync state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_athlete_profile(self, profile: AthleteProfile) -> None:
        """Upsert the single-athlete profile record."""

        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO athlete_profile (
                    athlete_id, username, firstname, lastname, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(athlete_id) DO UPDATE SET
                    username = excluded.username,
                    firstname = excluded.firstname,
                    lastname = excluded.lastname,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.athlete_id,
                    profile.username,
                    profile.firstname,
                    profile.lastname,
                    json.dumps(profile.raw_payload),
                    now,
                ),
            )
            connection.commit()

    def get_athlete_profile(self) -> AthleteProfile | None:
        """Return the stored athlete profile, if one exists."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT athlete_id, username, firstname, lastname, raw_json FROM athlete_profile LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return AthleteProfile(
            athlete_id=int(row["athlete_id"]),
            username=row["username"],
            firstname=row["firstname"],
            lastname=row["lastname"],
            raw_payload=json.loads(row["raw_json"]),
        )

    def save_tokens(self, tokens: OAuthTokenBundle) -> None:
        """Persist the latest OAuth tokens for the configured athlete."""

        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_tokens (
                    athlete_id, access_token, refresh_token, expires_at, scope, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(athlete_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    scope = excluded.scope,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    tokens.athlete_id,
                    tokens.access_token,
                    tokens.refresh_token,
                    tokens.expires_at,
                    tokens.scope,
                    json.dumps(tokens.raw_payload),
                    now,
                ),
            )
            connection.commit()

    def get_tokens(self) -> OAuthTokenBundle | None:
        """Return the stored token set, if available."""

        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT athlete_id, access_token, refresh_token, expires_at, scope, raw_json
                FROM oauth_tokens
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return OAuthTokenBundle(
            athlete_id=int(row["athlete_id"]),
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=int(row["expires_at"]),
            scope=row["scope"],
            raw_payload=json.loads(row["raw_json"]),
        )

    def upsert_activity_bundle(self, activity: ActivityRecord) -> None:
        """Persist a complete activity bundle and replace nested data."""

        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO activities (
                    activity_id, athlete_id, name, sport_type, start_date, timezone,
                    distance_meters, moving_time_seconds, elapsed_time_seconds,
                    total_elevation_gain_meters, average_speed_mps, max_speed_mps,
                    average_heartrate, max_heartrate, average_watts, weighted_average_watts,
                    kilojoules, suffer_score, trainer, commute, manual, is_private,
                    deleted, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    athlete_id = excluded.athlete_id,
                    name = excluded.name,
                    sport_type = excluded.sport_type,
                    start_date = excluded.start_date,
                    timezone = excluded.timezone,
                    distance_meters = excluded.distance_meters,
                    moving_time_seconds = excluded.moving_time_seconds,
                    elapsed_time_seconds = excluded.elapsed_time_seconds,
                    total_elevation_gain_meters = excluded.total_elevation_gain_meters,
                    average_speed_mps = excluded.average_speed_mps,
                    max_speed_mps = excluded.max_speed_mps,
                    average_heartrate = excluded.average_heartrate,
                    max_heartrate = excluded.max_heartrate,
                    average_watts = excluded.average_watts,
                    weighted_average_watts = excluded.weighted_average_watts,
                    kilojoules = excluded.kilojoules,
                    suffer_score = excluded.suffer_score,
                    trainer = excluded.trainer,
                    commute = excluded.commute,
                    manual = excluded.manual,
                    is_private = excluded.is_private,
                    deleted = excluded.deleted,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    activity.activity_id,
                    activity.athlete_id,
                    activity.name,
                    activity.sport_type,
                    activity.start_date.isoformat(),
                    activity.timezone,
                    activity.distance_meters,
                    activity.moving_time_seconds,
                    activity.elapsed_time_seconds,
                    activity.total_elevation_gain_meters,
                    activity.average_speed_mps,
                    activity.max_speed_mps,
                    activity.average_heartrate,
                    activity.max_heartrate,
                    activity.average_watts,
                    activity.weighted_average_watts,
                    activity.kilojoules,
                    activity.suffer_score,
                    int(activity.trainer),
                    int(activity.commute),
                    int(activity.manual),
                    int(activity.is_private),
                    int(activity.deleted),
                    json.dumps(activity.raw_payload),
                    now,
                ),
            )

            connection.execute("DELETE FROM activity_zones WHERE activity_id = ?", (activity.activity_id,))
            connection.execute("DELETE FROM activity_laps WHERE activity_id = ?", (activity.activity_id,))
            connection.execute("DELETE FROM activity_streams WHERE activity_id = ?", (activity.activity_id,))

            connection.executemany(
                """
                INSERT INTO activity_zones (
                    activity_id, resource, zone_index, min_value, max_value, time_seconds, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        zone.activity_id,
                        zone.resource,
                        zone.zone_index,
                        zone.min_value,
                        zone.max_value,
                        zone.time_seconds,
                        json.dumps(zone.raw_payload),
                    )
                    for zone in activity.zones
                ],
            )
            connection.executemany(
                """
                INSERT INTO activity_laps (
                    lap_id, activity_id, lap_index, name, elapsed_time_seconds, moving_time_seconds,
                    distance_meters, average_speed_mps, average_heartrate, max_heartrate, average_watts,
                    pace_zone, split, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        lap.lap_id,
                        lap.activity_id,
                        lap.lap_index,
                        lap.name,
                        lap.elapsed_time_seconds,
                        lap.moving_time_seconds,
                        lap.distance_meters,
                        lap.average_speed_mps,
                        lap.average_heartrate,
                        lap.max_heartrate,
                        lap.average_watts,
                        lap.pace_zone,
                        lap.split,
                        json.dumps(lap.raw_payload),
                    )
                    for lap in activity.laps
                ],
            )
            connection.executemany(
                """
                INSERT INTO activity_streams (
                    activity_id, stream_key, data_json, series_type, original_size, resolution, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        stream.activity_id,
                        stream.stream_key,
                        json.dumps(stream.data),
                        stream.series_type,
                        stream.original_size,
                        stream.resolution,
                        json.dumps(stream.raw_payload),
                    )
                    for stream in activity.streams.values()
                ],
            )
            connection.commit()

    def mark_activity_deleted(self, activity_id: int) -> None:
        """Tombstone an activity while preserving the original payload."""

        with self.database.connect() as connection:
            connection.execute(
                "UPDATE activities SET deleted = 1, updated_at = ? WHERE activity_id = ?",
                (datetime.now(timezone.utc).isoformat(), activity_id),
            )
            connection.commit()

    def is_empty(self) -> bool:
        """Return whether the activity table is currently empty.

        Returns:
            bool: `True` when no activity rows exist, otherwise `False`.
        """

        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM activities").fetchone()
        return int(row["count"]) == 0

    def list_activities(self, include_deleted: bool = False) -> list[ActivityRecord]:
        """Load stored activities including nested zone, lap, and stream data.

        Parameters:
            include_deleted: When `True`, include tombstoned activities.

        Returns:
            list[ActivityRecord]: Fully hydrated activity bundles ordered newest first.
        """

        with self.database.connect() as connection:
            clause = "" if include_deleted else "WHERE deleted = 0"
            activity_rows = connection.execute(
                f"""
                SELECT *
                FROM activities
                {clause}
                ORDER BY start_date DESC
                """
            ).fetchall()
            zone_rows = connection.execute("SELECT * FROM activity_zones").fetchall()
            lap_rows = connection.execute("SELECT * FROM activity_laps ORDER BY lap_index ASC").fetchall()
            stream_rows = connection.execute("SELECT * FROM activity_streams").fetchall()

        zones_by_activity: dict[int, list[ActivityZone]] = {}
        for row in zone_rows:
            zone = ActivityZone(
                activity_id=int(row["activity_id"]),
                resource=row["resource"],
                zone_index=int(row["zone_index"]),
                min_value=row["min_value"],
                max_value=row["max_value"],
                time_seconds=int(row["time_seconds"]),
                raw_payload=json.loads(row["raw_json"]),
            )
            zones_by_activity.setdefault(zone.activity_id, []).append(zone)

        laps_by_activity: dict[int, list[ActivityLap]] = {}
        for row in lap_rows:
            lap = ActivityLap(
                lap_id=int(row["lap_id"]),
                activity_id=int(row["activity_id"]),
                lap_index=int(row["lap_index"]),
                name=row["name"],
                elapsed_time_seconds=int(row["elapsed_time_seconds"]),
                moving_time_seconds=int(row["moving_time_seconds"]),
                distance_meters=float(row["distance_meters"]),
                average_speed_mps=row["average_speed_mps"],
                average_heartrate=row["average_heartrate"],
                max_heartrate=row["max_heartrate"],
                average_watts=row["average_watts"],
                pace_zone=row["pace_zone"],
                split=row["split"],
                raw_payload=json.loads(row["raw_json"]),
            )
            laps_by_activity.setdefault(lap.activity_id, []).append(lap)

        streams_by_activity: dict[int, dict[str, ActivityStream]] = {}
        for row in stream_rows:
            stream = ActivityStream(
                activity_id=int(row["activity_id"]),
                stream_key=row["stream_key"],
                data=json.loads(row["data_json"]),
                series_type=row["series_type"],
                original_size=row["original_size"],
                resolution=row["resolution"],
                raw_payload=json.loads(row["raw_json"]),
            )
            streams_by_activity.setdefault(stream.activity_id, {})[stream.stream_key] = stream

        activities: list[ActivityRecord] = []
        for row in activity_rows:
            activities.append(
                ActivityRecord(
                    activity_id=int(row["activity_id"]),
                    athlete_id=int(row["athlete_id"]),
                    name=row["name"],
                    sport_type=row["sport_type"],
                    start_date=datetime.fromisoformat(row["start_date"]),
                    timezone=row["timezone"],
                    distance_meters=float(row["distance_meters"]),
                    moving_time_seconds=int(row["moving_time_seconds"]),
                    elapsed_time_seconds=int(row["elapsed_time_seconds"]),
                    total_elevation_gain_meters=row["total_elevation_gain_meters"],
                    average_speed_mps=row["average_speed_mps"],
                    max_speed_mps=row["max_speed_mps"],
                    average_heartrate=row["average_heartrate"],
                    max_heartrate=row["max_heartrate"],
                    average_watts=row["average_watts"],
                    weighted_average_watts=row["weighted_average_watts"],
                    kilojoules=row["kilojoules"],
                    suffer_score=row["suffer_score"],
                    trainer=bool(row["trainer"]),
                    commute=bool(row["commute"]),
                    manual=bool(row["manual"]),
                    is_private=bool(row["is_private"]),
                    deleted=bool(row["deleted"]),
                    raw_payload=json.loads(row["raw_json"]),
                    zones=zones_by_activity.get(int(row["activity_id"]), []),
                    laps=laps_by_activity.get(int(row["activity_id"]), []),
                    streams=streams_by_activity.get(int(row["activity_id"]), {}),
                )
            )

        return activities

    def get_latest_activity_start_date(self) -> datetime | None:
        """Return the most recent activity start time stored in the database.

        Returns:
            datetime | None: The latest non-deleted activity start timestamp, if any.
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT start_date FROM activities WHERE deleted = 0 ORDER BY start_date DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["start_date"])

    def set_sync_state(self, key: str, value: dict[str, Any]) -> None:
        """Persist a JSON sync-state blob.

        Parameters:
            key: Logical sync-state key such as `initial_backfill`.
            value: JSON-serializable state payload.

        Returns:
            None: The sync-state row is written in place.
        """

        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()

    def get_sync_state(self, key: str) -> dict[str, Any] | None:
        """Return a JSON sync-state blob by key, if present.

        Parameters:
            key: Logical sync-state key to load.

        Returns:
            dict[str, Any] | None: The decoded state payload, if present.
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM sync_state WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def record_webhook_event(self, payload: dict[str, Any], outcome: str) -> None:
        """Store a webhook payload for debugging and audit purposes.

        Parameters:
            payload: Raw webhook payload received from Strava.
            outcome: Short label describing how the event was processed.

        Returns:
            None: The webhook event row is written in place.
        """

        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO webhook_events (payload_json, processed_at, outcome)
                VALUES (?, ?, ?)
                """,
                (
                    json.dumps(payload),
                    datetime.now(timezone.utc).isoformat(),
                    outcome,
                ),
            )
            connection.commit()

    def activity_exists(self, activity_id: int) -> bool:
        """Return whether an activity is already stored locally.

        Parameters:
            activity_id: Strava activity identifier to look up.

        Returns:
            bool: `True` when the activity already exists in SQLite.

        Example:
            >>> repository.activity_exists(12345)
            False
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 AS present FROM activities WHERE activity_id = ? LIMIT 1",
                (activity_id,),
            ).fetchone()
        return row is not None

    def get_oldest_activity_start_date(self) -> datetime | None:
        """Return the oldest non-deleted activity start time stored locally.

        Returns:
            datetime | None: The oldest known activity timestamp, if any.
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT start_date FROM activities WHERE deleted = 0 ORDER BY start_date ASC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["start_date"])
