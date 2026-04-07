"""Tests for projecting local Strava activities into the existing APEX schema."""

from __future__ import annotations

from typing import Any

import httpx

from strava_activity_sync.services.apex_supabase_projector import ApexSupabaseProjector
from strava_activity_sync.services.sync_service import build_activity_record

from conftest import load_fixture


class FakeSupabaseResponse:
    """Small fake HTTP response used to test Supabase projection calls."""

    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else str(payload)
        self.content = b"" if payload is None else b"x"

    def json(self) -> Any:
        """Return the configured fake JSON payload."""

        return self._payload


class FakeSupabaseClient:
    """Context-managed fake HTTP client for Supabase REST interactions."""

    def __init__(self, responses: list[FakeSupabaseResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeSupabaseClient":
        """Return the fake client instance."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Close the context manager without extra work."""

    def request(self, method: str, url: str, headers=None, json=None) -> FakeSupabaseResponse:
        """Record the request and return the next queued fake response."""

        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
            }
        )
        return self.responses.pop(0)


def test_project_activity_creates_daily_log_and_inserts_activity(monkeypatch, settings) -> None:
    """Projecting an activity should create the day and insert one activity row."""

    settings.apex_supabase_url = "https://example.supabase.co"
    settings.apex_supabase_service_role_key = "service-role"
    settings.vite_supabase_user_id = "sergio"
    fake_client = FakeSupabaseClient(
        [
            FakeSupabaseResponse(200, {"id": "daily-log-1"}),
            FakeSupabaseResponse(200, []),
            FakeSupabaseResponse(201, None),
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    activity = build_activity_record(
        load_fixture("activity_detail.json"),
        load_fixture("zones.json"),
        load_fixture("laps.json"),
        load_fixture("streams.json"),
    )
    projector = ApexSupabaseProjector(settings)

    projector.project_activity(activity)

    assert fake_client.calls[0]["url"].endswith("/rest/v1/rpc/get_or_create_daily_log")
    assert fake_client.calls[1]["url"].endswith(
        f"/rest/v1/activities?select=id,gpx_url&gpx_url=eq.https%3A%2F%2Fwww.strava.com%2Factivities%2F{activity.activity_id}&limit=1"
    )
    assert fake_client.calls[2]["method"] == "POST"
    assert fake_client.calls[2]["json"]["daily_log_id"] == "daily-log-1"
    assert fake_client.calls[2]["json"]["gpx_url"].endswith(str(activity.activity_id))


def test_project_activity_updates_existing_row(monkeypatch, settings) -> None:
    """Projecting an existing Strava activity should patch the existing APEX row."""

    settings.apex_supabase_url = "https://example.supabase.co"
    settings.apex_supabase_service_role_key = "service-role"
    fake_client = FakeSupabaseClient(
        [
            FakeSupabaseResponse(200, {"id": "daily-log-1"}),
            FakeSupabaseResponse(200, [{"id": "existing-activity-uuid", "gpx_url": "https://www.strava.com/activities/12345"}]),
            FakeSupabaseResponse(204, None),
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: fake_client)

    activity = build_activity_record(
        load_fixture("activity_detail.json"),
        load_fixture("zones.json"),
        load_fixture("laps.json"),
        load_fixture("streams.json"),
    )
    projector = ApexSupabaseProjector(settings)

    projector.project_activity(activity)

    assert fake_client.calls[2]["method"] == "PATCH"
    assert fake_client.calls[2]["url"].endswith("/rest/v1/activities?id=eq.existing-activity-uuid")
