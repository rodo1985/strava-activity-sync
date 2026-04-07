"""Projection helpers for mirroring Strava activities into the APEX Supabase schema."""

from __future__ import annotations

from datetime import date
import logging
from typing import Any
from urllib.parse import quote

import httpx

from strava_activity_sync.config import Settings
from strava_activity_sync.domain.activity_features import build_activity_insight
from strava_activity_sync.domain.models import ActivityRecord


LOGGER = logging.getLogger(__name__)


class ApexSupabaseProjectorError(RuntimeError):
    """Raised when the APEX Supabase projection API returns an error."""


class ApexSupabaseProjector:
    """Project synced Strava activities into the existing APEX daily-log schema.

    The current APEX database does not yet include the later `strava_*` canonical
    tables, so this projector targets the already-running schema the user shared:
    it ensures the `daily_log` exists for the activity date and then inserts or
    updates one row in `activities`.

    Parameters:
        settings: Application settings containing Supabase connection details.

    Example:
        >>> projector = ApexSupabaseProjector(settings)
        >>> projector.enabled
        True
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        """Return whether the projector has enough configuration to run.

        Returns:
            bool: `True` when the Supabase URL and service-role key are configured.
        """

        return self.settings.has_apex_supabase_config

    def project_activity(self, activity: ActivityRecord) -> None:
        """Insert or update one Strava activity in the existing APEX schema.

        Parameters:
            activity: Normalized Strava activity already stored in the local mirror.

        Returns:
            None: The method projects the activity for side effects only.

        Raises:
            ApexSupabaseProjectorError: Raised when Supabase cannot create the
                daily log or persist the activity row.
        """

        if not self.enabled:
            return

        day_type = self._infer_day_type(activity)
        daily_log = self._get_or_create_daily_log(
            log_date=activity.start_date.date(),
            day_type=day_type,
            user_id=self.settings.vite_supabase_user_id,
        )
        gpx_url = self._build_strava_activity_url(activity.activity_id)
        payload = self._build_activity_payload(activity, daily_log_id=daily_log["id"], gpx_url=gpx_url)
        existing_activity = self._find_existing_activity(gpx_url=gpx_url)
        if existing_activity is None:
            self._insert_activity(payload)
            LOGGER.info("Projected Strava activity into APEX.", extra={"activity_id": activity.activity_id})
            return

        self._update_activity(existing_activity_id=existing_activity["id"], payload=payload)
        LOGGER.info("Updated projected Strava activity in APEX.", extra={"activity_id": activity.activity_id})

    def project_activities(self, activities: list[ActivityRecord]) -> list[int]:
        """Project a list of local activities into the APEX schema.

        Parameters:
            activities: Local activity records that should appear in the APEX app.

        Returns:
            list[int]: Activity IDs that were processed successfully.

        Raises:
            ApexSupabaseProjectorError: Propagates projection failures from
                `project_activity`.
        """

        projected_ids: list[int] = []
        for activity in activities:
            if activity.deleted:
                # Deleted Strava rows should not keep feeding the APEX app.
                self.delete_activity(activity.activity_id)
                continue
            self.project_activity(activity)
            projected_ids.append(activity.activity_id)
        return projected_ids

    def delete_activity(self, activity_id: int) -> None:
        """Delete a projected activity from APEX when Strava deletes it upstream.

        Parameters:
            activity_id: Strava activity identifier used to reconstruct the APEX lookup.

        Returns:
            None: The delete is performed for side effects only.

        Raises:
            ApexSupabaseProjectorError: Raised when Supabase rejects the delete call.
        """

        if not self.enabled:
            return

        gpx_url = self._build_strava_activity_url(activity_id)
        encoded_url = quote(gpx_url, safe="")
        self._request(
            "DELETE",
            f"/rest/v1/activities?gpx_url=eq.{encoded_url}",
            expect_json=False,
        )

    def _infer_day_type(self, activity: ActivityRecord) -> str:
        """Infer the APEX day type from deterministic Strava load metrics.

        Parameters:
            activity: Activity record used to derive the training-day intensity.

        Returns:
            str: One of the existing APEX `day_type` enum values.
        """

        insight = build_activity_insight(activity)
        if "race" in insight.tags:
            return "race"
        if insight.load_score >= 180:
            return "hard"
        if insight.load_score >= 70:
            return "moderate"
        if insight.load_score > 0:
            return "light"
        return "rest"

    def _get_or_create_daily_log(self, *, log_date: date, day_type: str, user_id: str) -> dict[str, Any]:
        """Call the existing Supabase helper function to ensure the day exists.

        Parameters:
            log_date: Calendar day that should contain the projected activity.
            day_type: APEX day type passed to the helper function.
            user_id: User identifier used by the APEX schema.

        Returns:
            dict[str, Any]: The `daily_log` row returned by the database function.

        Raises:
            ApexSupabaseProjectorError: Raised when Supabase does not return a
                valid `daily_log` row.
        """

        payload = {
            "p_date": log_date.isoformat(),
            "p_day_type": day_type,
            "p_user_id": user_id,
        }
        result = self._request("POST", "/rest/v1/rpc/get_or_create_daily_log", json=payload)
        if not isinstance(result, dict) or "id" not in result:
            raise ApexSupabaseProjectorError("Supabase did not return a valid daily_log row.")
        return result

    def _find_existing_activity(self, *, gpx_url: str) -> dict[str, Any] | None:
        """Return the existing projected APEX activity for a Strava URL when present.

        Parameters:
            gpx_url: Stable Strava activity URL stored in the `gpx_url` column.

        Returns:
            dict[str, Any] | None: Existing activity row or `None` when missing.
        """

        encoded_url = quote(gpx_url, safe="")
        result = self._request(
            "GET",
            f"/rest/v1/activities?select=id,gpx_url&gpx_url=eq.{encoded_url}&limit=1",
        )
        if not isinstance(result, list) or not result:
            return None
        return result[0]

    def _insert_activity(self, payload: dict[str, Any]) -> None:
        """Insert a new activity row into the APEX `activities` table.

        Parameters:
            payload: Prepared row payload matching the current APEX schema.

        Returns:
            None: The insert runs for side effects only.
        """

        self._request(
            "POST",
            "/rest/v1/activities",
            json=payload,
            prefer="return=minimal",
            expect_json=False,
        )

    def _update_activity(self, *, existing_activity_id: str, payload: dict[str, Any]) -> None:
        """Patch an existing APEX activity row in place.

        Parameters:
            existing_activity_id: UUID of the existing `activities` row.
            payload: Prepared row payload matching the current APEX schema.

        Returns:
            None: The update runs for side effects only.
        """

        self._request(
            "PATCH",
            f"/rest/v1/activities?id=eq.{existing_activity_id}",
            json=payload,
            prefer="return=minimal",
            expect_json=False,
        )

    def _build_activity_payload(self, activity: ActivityRecord, *, daily_log_id: str, gpx_url: str) -> dict[str, Any]:
        """Build the JSON payload expected by the current APEX `activities` table.

        Parameters:
            activity: Normalized Strava activity to project.
            daily_log_id: Existing or newly created APEX daily log UUID.
            gpx_url: Stable Strava activity URL used as the external identifier.

        Returns:
            dict[str, Any]: JSON payload ready for Supabase REST writes.
        """

        insight = build_activity_insight(activity)
        return {
            "daily_log_id": daily_log_id,
            "title": activity.name,
            "sport": self._map_sport(activity.sport_type),
            "calories": int(round(activity.kilojoules or 0)),
            "distance": activity.distance_kilometers,
            "distance_unit": "km",
            "elevation": int(round(activity.total_elevation_gain_meters or 0)),
            "moving_time": self._format_duration(activity.moving_time_seconds),
            "avg_hr": int(round(activity.average_heartrate)) if activity.average_heartrate is not None else None,
            "extra_stats": self._build_extra_stats(activity, insight.load_score, insight.load_source),
            "zones": self._build_zone_summary(activity),
            "achievements": insight.tags,
            # `gpx_url` already exists in the user's current schema, so it is the
            # least invasive place to keep a stable Strava pointer before the
            # richer `external_id` migration is applied.
            "gpx_url": gpx_url,
        }

    def _build_extra_stats(
        self,
        activity: ActivityRecord,
        load_score: float,
        load_source: str,
    ) -> list[dict[str, Any]]:
        """Build the `extra_stats` card payload used by the APEX frontend.

        Parameters:
            activity: Normalized Strava activity.
            load_score: Deterministic load score computed from the activity.
            load_source: Explanation of how the load score was derived.

        Returns:
            list[dict[str, Any]]: Card-ready stat rows for the APEX UI.
        """

        stats = [
            {"label": "Load", "value": f"{load_score:.1f} ({load_source})"},
            {"label": "Distance", "value": f"{activity.distance_kilometers:.2f} km"},
            {"label": "Moving time", "value": self._format_duration(activity.moving_time_seconds)},
        ]
        if activity.total_elevation_gain_meters is not None:
            stats.append({"label": "Elevation", "value": f"{int(round(activity.total_elevation_gain_meters))} m"})
        if activity.average_watts is not None:
            stats.append({"label": "Avg power", "value": f"{int(round(activity.average_watts))} W"})
        return stats

    def _build_zone_summary(self, activity: ActivityRecord) -> list[dict[str, Any]]:
        """Convert stored zone rows into the compact APEX zone-card format.

        Parameters:
            activity: Normalized Strava activity with nested zone data.

        Returns:
            list[dict[str, Any]]: Zone summary rows ready for the APEX UI.
        """

        return [
            {
                "zone": f"{zone.resource} {zone.zone_index}",
                "pct": zone.time_seconds,
                "color": self._zone_color(zone.zone_index),
            }
            for zone in activity.zones
        ]

    def _map_sport(self, sport_type: str) -> str:
        """Map a Strava sport type into the current APEX sport enum.

        Parameters:
            sport_type: Upstream Strava sport type.

        Returns:
            str: Existing `activities.sport` enum value.
        """

        normalized = sport_type.lower()
        if "ride" in normalized or "cycle" in normalized:
            return "cycling"
        if normalized in {"run", "trailrun"}:
            return "running"
        if normalized == "walk":
            return "walking"
        if normalized == "hike":
            return "hiking"
        if normalized == "swim":
            return "swimming"
        if normalized in {"weighttraining", "workout"}:
            return "strength"
        return "default"

    def _format_duration(self, seconds: int) -> str:
        """Format a duration in the `H:MM:SS` style used by the APEX app.

        Parameters:
            seconds: Activity duration in seconds.

        Returns:
            str: Human-readable duration string.
        """

        hours, remainder = divmod(max(seconds, 0), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"

    def _zone_color(self, zone_index: int) -> str:
        """Return a stable UI color for a zone index.

        Parameters:
            zone_index: Numeric zone index from Strava.

        Returns:
            str: Hex color string used by the consuming frontend.
        """

        palette = [
            "#6b7280",
            "#22c55e",
            "#06b6d4",
            "#3b82f6",
            "#f59e0b",
            "#f97316",
            "#ef4444",
            "#a855f7",
        ]
        return palette[min(zone_index, len(palette) - 1)]

    def _build_strava_activity_url(self, activity_id: int) -> str:
        """Build the canonical Strava web URL for an activity.

        Parameters:
            activity_id: Strava activity identifier.

        Returns:
            str: Stable Strava activity URL.
        """

        return f"https://www.strava.com/activities/{activity_id}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        prefer: str | None = None,
        expect_json: bool = True,
    ) -> Any:
        """Send one authenticated request to the Supabase REST API.

        Parameters:
            method: HTTP method to use.
            path: Relative REST path under the Supabase project URL.
            json: Optional JSON body for writes and RPC calls.
            prefer: Optional `Prefer` header value.
            expect_json: Whether the caller expects a JSON response body.

        Returns:
            Any: Parsed JSON payload, or `None` for minimal writes.

        Raises:
            ApexSupabaseProjectorError: Raised when Supabase responds with an
                unexpected non-success status code.
        """

        headers = {
            "apikey": self.settings.apex_supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.apex_supabase_service_role_key}",
            "Accept-Profile": self.settings.apex_supabase_schema,
            "Content-Profile": self.settings.apex_supabase_schema,
        }
        if prefer:
            headers["Prefer"] = prefer

        url = f"{self.settings.apex_supabase_url.rstrip('/')}{path}"
        with httpx.Client(timeout=30) as client:
            response = client.request(method, url, headers=headers, json=json)

        if response.status_code >= 400:
            raise ApexSupabaseProjectorError(
                f"Supabase request failed with status {response.status_code}: {response.text}"
            )

        if not expect_json or not response.content:
            return None
        return response.json()
