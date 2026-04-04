"""Domain models used across ingestion, storage, and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class OAuthTokenBundle:
    """OAuth tokens returned by Strava."""

    athlete_id: int
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class AthleteProfile:
    """Single-athlete profile stored in SQLite."""

    athlete_id: int
    username: str | None
    firstname: str | None
    lastname: str | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ActivityZone:
    """Time spent in a single heart-rate or power zone."""

    activity_id: int
    resource: str
    zone_index: int
    min_value: float | None
    max_value: float | None
    time_seconds: int
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ActivityLap:
    """Single lap or split associated with an activity."""

    lap_id: int
    activity_id: int
    lap_index: int
    name: str | None
    elapsed_time_seconds: int
    moving_time_seconds: int
    distance_meters: float
    average_speed_mps: float | None
    average_heartrate: float | None
    max_heartrate: float | None
    average_watts: float | None
    pace_zone: int | None
    split: int | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ActivityStream:
    """Stream payload stored for a single activity metric."""

    activity_id: int
    stream_key: str
    data: list[Any]
    series_type: str | None
    original_size: int | None
    resolution: str | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ActivityRecord:
    """Full activity bundle used for analytics and rendering."""

    activity_id: int
    athlete_id: int
    name: str
    sport_type: str
    start_date: datetime
    timezone: str | None
    distance_meters: float
    moving_time_seconds: int
    elapsed_time_seconds: int
    total_elevation_gain_meters: float | None
    average_speed_mps: float | None
    max_speed_mps: float | None
    average_heartrate: float | None
    max_heartrate: float | None
    average_watts: float | None
    weighted_average_watts: float | None
    kilojoules: float | None
    suffer_score: float | None
    trainer: bool
    commute: bool
    manual: bool
    is_private: bool
    deleted: bool
    raw_payload: dict[str, Any]
    zones: list[ActivityZone] = field(default_factory=list)
    laps: list[ActivityLap] = field(default_factory=list)
    streams: dict[str, ActivityStream] = field(default_factory=dict)

    @property
    def distance_kilometers(self) -> float:
        """Return the activity distance in kilometers."""

        return round(self.distance_meters / 1000.0, 2)

    @property
    def moving_time_minutes(self) -> float:
        """Return the moving time in minutes."""

        return round(self.moving_time_seconds / 60.0, 1)

    @property
    def elapsed_time_minutes(self) -> float:
        """Return the elapsed time in minutes."""

        return round(self.elapsed_time_seconds / 60.0, 1)


@dataclass(slots=True)
class ActivityEvent:
    """Webhook event describing a Strava activity mutation."""

    aspect_type: str
    object_id: int
    object_type: str
    owner_id: int
    event_time: int
    updates: dict[str, Any]
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ActivityInsight:
    """Derived activity information used by renderers and tests."""

    activity: ActivityRecord
    load_score: float
    load_source: str
    tags: list[str]
    interval_summary: str | None
