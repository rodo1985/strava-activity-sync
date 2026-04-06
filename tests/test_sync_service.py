"""Tests for synchronization flows and webhook handling."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from strava_activity_sync.app import create_app
from strava_activity_sync.domain.models import AthleteProfile, OAuthTokenBundle
from strava_activity_sync.services.backfill_service import BackfillService
from strava_activity_sync.services.sync_service import SyncService

from conftest import load_fixture


class FakeStravaClient:
    """Fake Strava client returning fixture-driven responses.

    The fake client models the real client's summary pagination and date filtering so
    tests can exercise recent-first sync and historical fallback behavior.
    """

    def __init__(self) -> None:
        self.details = {
            12345: load_fixture("activity_detail.json"),
            67890: load_fixture("activity_detail_second.json"),
        }
        self.activity_order = [12345, 67890]
        self.refresh_called = False
        self.stream_call_ids: list[int] = []

    def refresh_token(self, refresh_token: str, athlete_id: int | None = None) -> OAuthTokenBundle:
        """Return a refreshed token bundle for tests.

        Parameters:
            refresh_token: Refresh token passed by the sync service.
            athlete_id: Optional fallback athlete identifier.

        Returns:
            OAuthTokenBundle: Refreshed token payload for follow-up calls.
        """

        del athlete_id
        self.refresh_called = True
        return OAuthTokenBundle(
            athlete_id=101,
            access_token="fresh-access-token",
            refresh_token="fresh-refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={"refresh_token": refresh_token},
        )

    def iter_activities(
        self,
        access_token: str,
        after=None,
        before=None,
        per_page: int = 200,
        max_pages: int | None = None,
    ):
        """Yield filtered and paginated activity summaries for sync tests.

        Parameters:
            access_token: Ignored fake access token.
            after: Optional lower time bound.
            before: Optional upper time bound.
            per_page: Maximum number of activities per yielded page.
            max_pages: Optional cap on how many pages to yield.

        Yields:
            dict: Minimal Strava activity summary payloads containing only `id`.
        """

        del access_token

        after_dt = self._coerce_datetime(after)
        before_dt = self._coerce_datetime(before)

        activity_ids = sorted(
            self.activity_order,
            key=self._activity_start_date,
            reverse=True,
        )
        filtered_ids: list[int] = []
        for activity_id in activity_ids:
            start_date = self._activity_start_date(activity_id)
            if after_dt is not None and start_date < after_dt:
                continue
            if before_dt is not None and start_date >= before_dt:
                continue
            filtered_ids.append(activity_id)

        page = 0
        for start_index in range(0, len(filtered_ids), per_page):
            page += 1
            if max_pages is not None and page > max_pages:
                break
            page_ids = filtered_ids[start_index : start_index + per_page]
            for activity_id in page_ids:
                yield {"id": activity_id}

    def get_activity(self, access_token: str, activity_id: int) -> dict:
        """Return a fixture detail payload for the requested activity.

        Parameters:
            access_token: Ignored fake access token.
            activity_id: Activity identifier to load.

        Returns:
            dict: Deep-copied activity detail payload.
        """

        del access_token
        return deepcopy(self.details[activity_id])

    def get_activity_zones(self, access_token: str, activity_id: int) -> list[dict]:
        """Return fixture zone data for an activity.

        Parameters:
            access_token: Ignored fake access token.
            activity_id: Activity identifier to load.

        Returns:
            list[dict]: Deep-copied activity zone payloads.
        """

        del access_token, activity_id
        return deepcopy(load_fixture("zones.json"))

    def get_activity_laps(self, access_token: str, activity_id: int) -> list[dict]:
        """Return fixture lap data for an activity.

        Parameters:
            access_token: Ignored fake access token.
            activity_id: Activity identifier to load.

        Returns:
            list[dict]: Deep-copied activity lap payloads.
        """

        del access_token, activity_id
        return deepcopy(load_fixture("laps.json"))

    def get_activity_streams(self, access_token: str, activity_id: int) -> dict:
        """Return fixture stream data and record stream usage.

        Parameters:
            access_token: Ignored fake access token.
            activity_id: Activity identifier to load.

        Returns:
            dict: Deep-copied stream payloads for the requested activity.
        """

        del access_token
        self.stream_call_ids.append(activity_id)
        return deepcopy(load_fixture("streams.json"))

    def exchange_code(self, code: str) -> OAuthTokenBundle:
        """Return a fixture token bundle for the OAuth callback test.

        Parameters:
            code: OAuth code provided by the callback route.

        Returns:
            OAuthTokenBundle: Stored token bundle used by test routes.
        """

        return OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={"code": code},
        )

    def get_athlete(self, access_token: str) -> AthleteProfile:
        """Return a fixture athlete profile.

        Parameters:
            access_token: Ignored fake access token.

        Returns:
            AthleteProfile: Fixture-backed athlete profile for OAuth tests.
        """

        del access_token
        athlete = load_fixture("athlete.json")
        return AthleteProfile(
            athlete_id=athlete["id"],
            username=athlete["username"],
            firstname=athlete["firstname"],
            lastname=athlete["lastname"],
            raw_payload=athlete,
        )

    def build_authorize_url(self) -> str:
        """Return a fake authorize URL.

        Returns:
            str: Static authorize URL used by route tests.
        """

        return "https://www.strava.com/oauth/authorize?client_id=fake"

    def _activity_start_date(self, activity_id: int) -> datetime:
        """Return the activity start date for sorting and filtering tests.

        Parameters:
            activity_id: Activity identifier to inspect.

        Returns:
            datetime: Parsed timezone-aware start date for the activity.
        """

        return datetime.fromisoformat(self.details[activity_id]["start_date"].replace("Z", "+00:00"))

    @staticmethod
    def _coerce_datetime(value) -> datetime | None:
        """Convert mixed timestamp inputs into timezone-aware datetimes.

        Parameters:
            value: `datetime`, integer timestamp, or `None`.

        Returns:
            datetime | None: Normalized timestamp for comparisons.
        """

        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(int(value), tz=timezone.utc)


def test_initial_backfill_populates_empty_database(repository, render_service) -> None:
    """An empty database should be seeded with a bounded, stream-free batch."""

    fake_client = FakeStravaClient()
    repository.save_tokens(
        OAuthTokenBundle(
            athlete_id=101,
            access_token="expired-access-token",
            refresh_token="refresh-token",
            expires_at=1,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={},
        )
    )
    service = SyncService(repository, fake_client, render_service)

    result = service.maybe_run_initial_backfill(30)

    assert result is not None
    assert sorted(result.processed_activity_ids) == [12345, 67890]
    assert fake_client.refresh_called is True
    assert fake_client.stream_call_ids == []
    assert len(repository.list_activities()) == 2
    assert (render_service.exporter.export_directory / "dashboard.md").exists()


def test_webhook_create_update_and_delete(repository, render_service) -> None:
    """Webhook events should sync, refresh, and tombstone activities deterministically."""

    fake_client = FakeStravaClient()
    repository.save_tokens(
        OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={},
        )
    )
    service = SyncService(repository, fake_client, render_service)

    create_result = service.handle_webhook_event(load_fixture("webhook_create.json"))
    fake_client.details[12345] = load_fixture("activity_detail_updated.json")
    update_result = service.handle_webhook_event(load_fixture("webhook_update.json"))
    delete_result = service.handle_webhook_event(load_fixture("webhook_delete.json"))

    assert create_result is not None
    assert update_result is not None
    assert delete_result is not None
    remaining = repository.list_activities()
    assert remaining == []
    all_activities = repository.list_activities(include_deleted=True)
    assert len(all_activities) == 1
    assert all_activities[0].deleted is True
    assert all_activities[0].name == "Morning Run Intervals Updated"
    assert fake_client.stream_call_ids == [12345, 12345]


def test_reconciliation_is_idempotent(repository, render_service) -> None:
    """Repeated reconciliation runs should not duplicate activities."""

    fake_client = FakeStravaClient()
    repository.save_tokens(
        OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={},
        )
    )
    service = SyncService(repository, fake_client, render_service)

    first = service.reconcile(lookback_days=14)
    second = service.reconcile(lookback_days=14)

    assert len(first.processed_activity_ids) == 2
    assert len(second.processed_activity_ids) == 0
    assert len(repository.list_activities()) == 2
    assert fake_client.stream_call_ids == []


def test_reconciliation_falls_back_to_historical_when_recent_window_is_idle(repository, render_service) -> None:
    """Recent-first collection should use the historical page when nothing new is recent."""

    fake_client = FakeStravaClient()
    fake_client.details[24680] = deepcopy(load_fixture("activity_detail_second.json"))
    fake_client.details[24680]["id"] = 24680
    fake_client.details[24680]["name"] = "Older Aerobic Run"
    fake_client.details[24680]["start_date"] = "2026-03-10T07:00:00Z"
    fake_client.details[24680]["athlete"] = {"id": 101}
    fake_client.activity_order = [12345, 67890, 24680]
    repository.save_tokens(
        OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={},
        )
    )
    service = SyncService(repository, fake_client, render_service)

    # Seed the recent records first so the next reconciliation cycle has to fall
    # back to older history instead of reprocessing already-known recent items.
    service.sync_activity(12345, include_streams=False)
    service.sync_activity(67890, include_streams=False)
    fake_client.stream_call_ids.clear()

    result = service.reconcile(lookback_days=14)

    assert result.processed_activity_ids == [24680]
    assert len(repository.list_activities()) == 3
    assert fake_client.stream_call_ids == []
    assert repository.get_sync_state("reconciliation")["phase"] == "historical"


def test_startup_sync_checks_recent_window_even_when_database_is_not_empty(repository, render_service) -> None:
    """Startup sync should still look for recent unknown activities after a restart."""

    fake_client = FakeStravaClient()
    fake_client.details[24680] = deepcopy(load_fixture("activity_detail_second.json"))
    fake_client.details[24680]["id"] = 24680
    fake_client.details[24680]["name"] = "Fresh Recovery Ride"
    fake_client.details[24680]["sport_type"] = "Ride"
    fake_client.details[24680]["start_date"] = "2026-04-05T07:15:00Z"
    fake_client.details[24680]["athlete"] = {"id": 101}
    fake_client.activity_order = [24680, 12345, 67890]
    repository.save_tokens(
        OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={},
        )
    )
    service = SyncService(repository, fake_client, render_service)

    service.sync_activity(12345, include_streams=False)
    result = service.run_startup_sync(lookback_days=30)

    assert result is not None
    assert result.processed_activity_ids == [24680, 67890]
    assert repository.get_sync_state("startup_sync")["trigger"] == "startup"
    assert len(repository.list_activities()) == 3


def test_app_webhook_routes(settings, monkeypatch) -> None:
    """The FastAPI app should accept webhook verification and delivery requests."""

    import strava_activity_sync.app as app_module

    fake_client = FakeStravaClient()
    original_build_services = app_module.build_services

    def fake_build_services(_settings=None):
        """Return app services wired to the fake Strava client for route tests."""

        services = original_build_services(settings)
        services.strava_client = fake_client
        services.sync_service = SyncService(
            services.repository,
            fake_client,
            services.render_service,
            sync_batch_size=settings.sync_batch_size,
        )
        services.backfill_service = BackfillService(services.sync_service)
        services.scheduler.shutdown()
        return services

    monkeypatch.setattr(app_module, "build_services", fake_build_services)

    application = create_app(settings)
    services = application.state.services
    services.repository.save_tokens(
        OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={},
        )
    )
    client = TestClient(application)

    verify_response = client.get(
        "/webhooks/strava",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "abc123",
            "hub.verify_token": settings.strava_webhook_verify_token,
        },
    )
    health_response = client.get("/health")
    post_response = client.post("/webhooks/strava", json=load_fixture("webhook_create.json"))

    assert verify_response.status_code == 200
    assert verify_response.json() == {"hub.challenge": "abc123"}
    assert health_response.status_code == 200
    assert "last_sync_at" in health_response.json()
    assert post_response.status_code == 200
    assert post_response.json()["processed_activity_ids"] == [12345]
