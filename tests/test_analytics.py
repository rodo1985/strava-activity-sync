"""Unit tests for deterministic activity analytics helpers."""

from strava_activity_sync.domain.activity_features import build_activity_insight, compute_load_score
from strava_activity_sync.services.sync_service import build_activity_record

from conftest import load_fixture


def test_load_score_prefers_suffer_score() -> None:
    """The load score should prefer Strava's suffer score when available."""

    activity = build_activity_record(
        load_fixture("activity_detail_second.json"),
        load_fixture("zones.json"),
        load_fixture("laps.json"),
        load_fixture("streams.json"),
    )

    score, source = compute_load_score(activity)

    assert score == 82.0
    assert source == "suffer_score"


def test_load_score_falls_back_to_weighted_power_zones() -> None:
    """The load score should use weighted power zones before duration fallback."""

    detail = load_fixture("activity_detail.json")
    detail["suffer_score"] = None
    activity = build_activity_record(
        detail,
        load_fixture("zones.json"),
        load_fixture("laps.json"),
        load_fixture("streams.json"),
    )

    score, source = compute_load_score(activity)

    assert score > 0
    assert source == "weighted_power_zones"


def test_interval_workout_gets_interval_tag() -> None:
    """Structured hard and easy laps should be tagged as intervals."""

    activity = build_activity_record(
        load_fixture("activity_detail.json"),
        load_fixture("zones.json"),
        load_fixture("laps.json"),
        load_fixture("streams.json"),
    )

    insight = build_activity_insight(activity)

    assert "intervals" in insight.tags
    assert insight.interval_summary is not None

