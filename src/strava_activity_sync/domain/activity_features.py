"""Derived activity metrics and classification heuristics."""

from __future__ import annotations

from statistics import median

from strava_activity_sync.domain.models import ActivityInsight, ActivityLap, ActivityRecord


def compute_load_score(activity: ActivityRecord) -> tuple[float, str]:
    """Compute a deterministic load score for an activity."""

    if activity.suffer_score is not None:
        return round(float(activity.suffer_score), 2), "suffer_score"

    power_zones = [zone for zone in activity.zones if zone.resource == "power"]
    if power_zones:
        return _weighted_zone_load(power_zones), "weighted_power_zones"

    heartrate_zones = [zone for zone in activity.zones if zone.resource == "heartrate"]
    if heartrate_zones:
        return _weighted_zone_load(heartrate_zones), "weighted_heartrate_zones"

    duration_hours = activity.moving_time_seconds / 3600.0
    return round(duration_hours * 50.0, 2), "duration_fallback"


def _weighted_zone_load(zones: list) -> float:
    """Convert time-in-zone data into a single weighted load score."""

    total = 0.0
    for zone in zones:
        total += (zone.zone_index + 1) * max(zone.time_seconds, 0)
    return round(total / 60.0, 2)


def detect_interval_summary(activity: ActivityRecord) -> str | None:
    """Return a compact interval summary when the workout looks interval-driven."""

    name_lower = activity.name.lower()
    if any(keyword in name_lower for keyword in ("interval", "repeats", "track", "vo2")):
        return "Activity name indicates an interval session."

    scored_laps = _scored_laps(activity.laps)
    if len(scored_laps) < 4:
        return None

    lap_scores = [score for _, score in scored_laps]
    median_score = median(lap_scores)
    hard_laps = [lap for lap, score in scored_laps if score >= median_score * 1.15]
    easy_laps = [lap for lap, score in scored_laps if score <= median_score * 0.9]
    if len(hard_laps) >= 2 and len(easy_laps) >= 2:
        return (
            f"Detected {len(hard_laps)} hard laps and {len(easy_laps)} easier recovery laps, "
            "which matches a likely interval pattern."
        )

    return None


def _scored_laps(laps: list[ActivityLap]) -> list[tuple[ActivityLap, float]]:
    """Score laps using the richest available intensity metric."""

    scored: list[tuple[ActivityLap, float]] = []
    for lap in laps:
        score = 0.0
        if lap.average_watts is not None:
            score = lap.average_watts
        elif lap.average_heartrate is not None:
            score = lap.average_heartrate
        elif lap.average_speed_mps is not None:
            score = lap.average_speed_mps
        if score > 0:
            scored.append((lap, score))
    return scored


def classify_tags(activity: ActivityRecord, load_score: float, interval_summary: str | None) -> list[str]:
    """Classify an activity into deterministic agent-friendly tags."""

    tags: set[str] = set()
    name_lower = activity.name.lower()

    if activity.commute:
        tags.add("commute")
    if interval_summary:
        tags.add("intervals")
    if any(keyword in name_lower for keyword in ("tempo", "threshold")):
        tags.add("tempo")
    if any(keyword in name_lower for keyword in ("race", "marathon", "triathlon")):
        tags.add("race")

    if _is_long_endurance(activity):
        tags.add("long_endurance")

    if load_score <= 25 and activity.moving_time_seconds <= 3600:
        tags.add("recovery")

    if not tags and load_score >= 60 and activity.moving_time_seconds >= 2700:
        tags.add("steady_load")

    return sorted(tags)


def _is_long_endurance(activity: ActivityRecord) -> bool:
    """Return whether an activity should be tagged as a long endurance session."""

    sport = activity.sport_type.lower()
    if sport in {"run", "trailrun"}:
        return activity.moving_time_seconds >= 5400
    if sport in {"ride", "virtualride", "ebikeride"}:
        return activity.moving_time_seconds >= 9000
    if sport in {"swim"}:
        return activity.moving_time_seconds >= 3600
    return activity.moving_time_seconds >= 7200


def build_activity_insight(activity: ActivityRecord) -> ActivityInsight:
    """Build the derived view of an activity used by downstream renderers."""

    load_score, load_source = compute_load_score(activity)
    interval_summary = detect_interval_summary(activity)
    tags = classify_tags(activity, load_score, interval_summary)
    return ActivityInsight(
        activity=activity,
        load_score=load_score,
        load_source=load_source,
        tags=tags,
        interval_summary=interval_summary,
    )

