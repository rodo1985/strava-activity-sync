"""HTTP client wrapper for Strava OAuth and activity endpoints."""

from __future__ import annotations

import logging
from typing import Any, Iterable
from urllib.parse import urlencode

import httpx

from strava_activity_sync.config import Settings
from strava_activity_sync.domain.models import AthleteProfile, OAuthTokenBundle


LOGGER = logging.getLogger(__name__)


class StravaClientError(RuntimeError):
    """Raised when the Strava API returns an unexpected response."""


class StravaClient:
    """Small Strava API client focused on deterministic sync operations."""

    AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
    TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
    API_BASE_URL = "https://www.strava.com/api/v3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_authorize_url(self) -> str:
        """Build the OAuth authorization URL for the connected athlete."""

        query = urlencode(
            {
                "client_id": self.settings.strava_client_id,
                "redirect_uri": self.settings.strava_redirect_uri,
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": self.settings.strava_scopes,
            }
        )
        return f"{self.AUTHORIZE_URL}?{query}"

    def exchange_code(self, code: str) -> OAuthTokenBundle:
        """Exchange an OAuth code for tokens."""

        payload = {
            "client_id": self.settings.strava_client_id,
            "client_secret": self.settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        response = self._request("POST", self.TOKEN_URL, data=payload, authenticated=False)
        athlete_id = int(response["athlete"]["id"])
        return OAuthTokenBundle(
            athlete_id=athlete_id,
            access_token=response["access_token"],
            refresh_token=response["refresh_token"],
            expires_at=int(response["expires_at"]),
            scope=self.settings.strava_scopes,
            raw_payload=response,
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokenBundle:
        """Refresh an expired Strava access token."""

        payload = {
            "client_id": self.settings.strava_client_id,
            "client_secret": self.settings.strava_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        response = self._request("POST", self.TOKEN_URL, data=payload, authenticated=False)
        athlete_id = int(response["athlete"]["id"])
        return OAuthTokenBundle(
            athlete_id=athlete_id,
            access_token=response["access_token"],
            refresh_token=response["refresh_token"],
            expires_at=int(response["expires_at"]),
            scope=self.settings.strava_scopes,
            raw_payload=response,
        )

    def get_athlete(self, access_token: str) -> AthleteProfile:
        """Fetch the profile for the currently authenticated athlete."""

        response = self._request("GET", f"{self.API_BASE_URL}/athlete", access_token=access_token)
        return AthleteProfile(
            athlete_id=int(response["id"]),
            username=response.get("username"),
            firstname=response.get("firstname"),
            lastname=response.get("lastname"),
            raw_payload=response,
        )

    def iter_activities(
        self,
        access_token: str,
        after=None,
        before=None,
        per_page: int = 200,
        max_pages: int | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Iterate through paginated athlete activities.

        Parameters:
            access_token: Valid Strava access token for the athlete.
            after: Optional lower time bound accepted by Strava.
            before: Optional upper time bound accepted by Strava.
            per_page: Maximum number of activity summaries per page request.
            max_pages: Optional cap on the number of summary pages to inspect.

        Returns:
            Iterable[dict[str, Any]]: Activity summary payloads ordered by Strava.

        Raises:
            StravaClientError: Propagates API failures from `_request`.
        """

        page = 1
        while True:
            params: dict[str, Any] = {"page": page, "per_page": per_page}
            if after is not None:
                params["after"] = int(after.timestamp()) if hasattr(after, "timestamp") else int(after)
            if before is not None:
                params["before"] = int(before.timestamp()) if hasattr(before, "timestamp") else int(before)
            response = self._request(
                "GET",
                f"{self.API_BASE_URL}/athlete/activities",
                access_token=access_token,
                params=params,
            )
            if not response:
                break
            for item in response:
                yield item
            if len(response) < per_page:
                break
            if max_pages is not None and page >= max_pages:
                break
            page += 1

    def get_activity(self, access_token: str, activity_id: int) -> dict[str, Any]:
        """Fetch a detailed activity payload."""

        return self._request(
            "GET",
            f"{self.API_BASE_URL}/activities/{activity_id}",
            access_token=access_token,
            params={"include_all_efforts": True},
        )

    def get_activity_zones(self, access_token: str, activity_id: int) -> list[dict[str, Any]]:
        """Fetch heart-rate and power zone data for an activity."""

        return self._request(
            "GET",
            f"{self.API_BASE_URL}/activities/{activity_id}/zones",
            access_token=access_token,
        )

    def get_activity_laps(self, access_token: str, activity_id: int) -> list[dict[str, Any]]:
        """Fetch lap data for an activity."""

        return self._request(
            "GET",
            f"{self.API_BASE_URL}/activities/{activity_id}/laps",
            access_token=access_token,
        )

    def get_activity_streams(self, access_token: str, activity_id: int) -> dict[str, Any]:
        """Fetch the stream bundle used for interval and pacing analysis."""

        return self._request(
            "GET",
            f"{self.API_BASE_URL}/activities/{activity_id}/streams",
            access_token=access_token,
            params={
                "keys": "time,distance,heartrate,watts,velocity_smooth,altitude",
                "key_by_type": "true",
            },
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        access_token: str | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Send an HTTP request to Strava and return the parsed JSON body."""

        headers = {}
        if authenticated:
            if not access_token:
                raise StravaClientError("An access token is required for authenticated Strava requests.")
            headers["Authorization"] = f"Bearer {access_token}"

        timeout = self.settings.strava_request_timeout_seconds
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, headers=headers, params=params, data=data)

        if response.status_code >= 400:
            LOGGER.error("Strava request failed", extra={"url": url, "status_code": response.status_code})
            raise StravaClientError(
                f"Strava API request failed with status {response.status_code}: {response.text}"
            )

        return response.json()
