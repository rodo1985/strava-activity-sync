"""Tests for the Strava HTTP client wrapper."""

from typing import Any

import httpx

from strava_activity_sync.config import Settings
from strava_activity_sync.services.strava_client import StravaClient


class FakeResponse:
    """Tiny fake HTTP response used to test the Strava client wrapper."""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Any:
        """Return the preconfigured payload."""

        return self._payload


class FakeHttpClient:
    """Context-managed fake HTTP client that replays a response queue."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeHttpClient":
        """Return the active fake client."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Close the context manager without extra work."""

    def request(self, method: str, url: str, headers=None, params=None, data=None) -> FakeResponse:
        """Record the request and pop the next fake response."""

        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "data": data,
            }
        )
        return self.responses.pop(0)


def test_refresh_token_returns_bundle(monkeypatch, settings: Settings) -> None:
    """Refreshing a token should parse the Strava response into a bundle."""

    fake_client = FakeHttpClient(
        [
            FakeResponse(
                200,
                {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_at": 4102444800,
                    "athlete": {"id": 101},
                },
            )
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    client = StravaClient(settings)
    bundle = client.refresh_token("old-refresh-token")

    assert bundle.access_token == "new-access-token"
    assert bundle.refresh_token == "new-refresh-token"
    assert bundle.athlete_id == 101


def test_iter_activities_paginate_until_empty(monkeypatch, settings: Settings) -> None:
    """The activity iterator should keep fetching pages until an empty page arrives."""

    fake_client = FakeHttpClient(
        [
            FakeResponse(200, [{"id": 1}, {"id": 2}]),
            FakeResponse(200, []),
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    client = StravaClient(settings)
    activities = list(client.iter_activities("token", per_page=2))

    assert activities == [{"id": 1}, {"id": 2}]
    assert fake_client.calls[0]["params"]["page"] == 1
    assert fake_client.calls[1]["params"]["page"] == 2


def test_verify_config_uses_configured_ca_bundle(tmp_path, settings: Settings) -> None:
    """The client should honor an explicit CA bundle path when configured."""

    ca_bundle = tmp_path / "custom-ca.pem"
    ca_bundle.write_text("dummy", encoding="utf-8")
    settings.strava_verify_ssl = True
    settings.strava_ca_bundle_path = str(ca_bundle)

    client = StravaClient(settings)

    assert client._build_verify_config() == str(ca_bundle)


def test_verify_config_disables_tls_when_requested(settings: Settings) -> None:
    """The client should return False when SSL verification is disabled."""

    settings.strava_verify_ssl = False
    settings.strava_ca_bundle_path = ""

    client = StravaClient(settings)

    assert client._build_verify_config() is False
