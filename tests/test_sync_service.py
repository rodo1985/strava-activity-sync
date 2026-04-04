"""Tests for synchronization flows and webhook handling."""

from copy import deepcopy

from fastapi.testclient import TestClient

from strava_activity_sync.app import create_app
from strava_activity_sync.domain.models import AthleteProfile, OAuthTokenBundle
from strava_activity_sync.services.backfill_service import BackfillService
from strava_activity_sync.services.sync_service import SyncService

from conftest import load_fixture


class FakeStravaClient:
    """Fake Strava client returning fixture-driven responses."""

    def __init__(self) -> None:
        self.details = {
            12345: load_fixture("activity_detail.json"),
            67890: load_fixture("activity_detail_second.json"),
        }
        self.refresh_called = False

    def refresh_token(self, refresh_token: str) -> OAuthTokenBundle:
        """Return a refreshed token bundle for tests."""

        self.refresh_called = True
        return OAuthTokenBundle(
            athlete_id=101,
            access_token="fresh-access-token",
            refresh_token="fresh-refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={"refresh_token": refresh_token},
        )

    def iter_activities(self, access_token: str, after=None, before=None, per_page: int = 200):
        """Yield a small fixed activity list for backfill and reconciliation tests."""

        yield {"id": 12345}
        yield {"id": 67890}

    def get_activity(self, access_token: str, activity_id: int) -> dict:
        """Return a fixture detail payload for the requested activity."""

        return deepcopy(self.details[activity_id])

    def get_activity_zones(self, access_token: str, activity_id: int) -> list[dict]:
        """Return fixture zone data."""

        return deepcopy(load_fixture("zones.json"))

    def get_activity_laps(self, access_token: str, activity_id: int) -> list[dict]:
        """Return fixture lap data."""

        return deepcopy(load_fixture("laps.json"))

    def get_activity_streams(self, access_token: str, activity_id: int) -> dict:
        """Return fixture stream data."""

        return deepcopy(load_fixture("streams.json"))

    def exchange_code(self, code: str) -> OAuthTokenBundle:
        """Return a fixture token bundle for the OAuth callback test."""

        return OAuthTokenBundle(
            athlete_id=101,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=4_102_444_800,
            scope="read,activity:read_all,profile:read_all",
            raw_payload={"code": code},
        )

    def get_athlete(self, access_token: str) -> AthleteProfile:
        """Return a fixture athlete profile."""

        athlete = load_fixture("athlete.json")
        return AthleteProfile(
            athlete_id=athlete["id"],
            username=athlete["username"],
            firstname=athlete["firstname"],
            lastname=athlete["lastname"],
            raw_payload=athlete,
        )

    def build_authorize_url(self) -> str:
        """Return a fake authorize URL."""

        return "https://www.strava.com/oauth/authorize?client_id=fake"


def test_initial_backfill_populates_empty_database(repository, render_service) -> None:
    """An empty database should be backfilled and exported on first run."""

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

    result = service.maybe_run_initial_backfill(365)

    assert result is not None
    assert sorted(result.processed_activity_ids) == [12345, 67890]
    assert fake_client.refresh_called is True
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

    first = service.reconcile(lookback_days=30)
    second = service.reconcile(lookback_days=30)

    assert len(first.processed_activity_ids) == 2
    assert len(second.processed_activity_ids) == 2
    assert len(repository.list_activities()) == 2


def test_app_webhook_routes(settings, monkeypatch) -> None:
    """The FastAPI app should accept webhook verification and delivery requests."""

    import strava_activity_sync.app as app_module

    fake_client = FakeStravaClient()
    original_build_services = app_module.build_services

    def fake_build_services(_settings=None):
        services = original_build_services(settings)
        services.strava_client = fake_client
        services.sync_service = SyncService(services.repository, fake_client, services.render_service)
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
    post_response = client.post("/webhooks/strava", json=load_fixture("webhook_create.json"))

    assert verify_response.status_code == 200
    assert verify_response.json() == {"hub.challenge": "abc123"}
    assert post_response.status_code == 200
    assert post_response.json()["processed_activity_ids"] == [12345]
