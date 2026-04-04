"""Aggregated training load calculations for rendered outputs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from strava_activity_sync.domain.activity_features import build_activity_insight
from strava_activity_sync.domain.models import ActivityInsight, ActivityRecord


@dataclass(slots=True)
class PeriodSummary:
    """Aggregated metrics for a specific time window."""

    label: str
    start: datetime
    end: datetime
    activity_count: int
    total_distance_km: float
    total_moving_time_hours: float
    total_elevation_gain_m: float
    total_load: float
    sport_breakdown: dict[str, dict[str, float]]
    zone_totals: dict[str, list[dict[str, float | int | None]]]
    activities: list[ActivityInsight]


@dataclass(slots=True)
class RenderContext:
    """All derived data required to render exports."""

    insights: list[ActivityInsight]
    last_7_days: PeriodSummary
    current_week: PeriodSummary
    previous_week: PeriodSummary
    last_14_days: PeriodSummary
    rolling_28_days: PeriodSummary
    month_to_date: PeriodSummary
    year_to_date: PeriodSummary
    notable_sessions: list[ActivityInsight]
    load_flags: list[str]


def build_render_context(
    activities: list[ActivityRecord],
    timezone_name: str,
    now: datetime | None = None,
) -> RenderContext:
    """Build a deterministic rendering context from stored activities."""

    tz = ZoneInfo(timezone_name)
    current_time = now.astimezone(tz) if now else datetime.now(tz)
    active_activities = sorted(
        [activity for activity in activities if not activity.deleted],
        key=lambda item: item.start_date,
        reverse=True,
    )
    insights = [build_activity_insight(activity) for activity in active_activities]

    current_week_start = current_time - timedelta(days=current_time.weekday())
    current_week_start = current_week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    previous_week_start = current_week_start - timedelta(days=7)
    month_start = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = current_time.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    last_7_days = summarize_period(
        "Last 7 days",
        insights,
        current_time - timedelta(days=7),
        current_time,
    )
    current_week = summarize_period("Current week", insights, current_week_start, current_time)
    previous_week = summarize_period(
        "Previous week",
        insights,
        previous_week_start,
        current_week_start,
    )
    last_14_days = summarize_period(
        "Last 14 days",
        insights,
        current_time - timedelta(days=14),
        current_time,
    )
    rolling_28_days = summarize_period(
        "Rolling 28 days",
        insights,
        current_time - timedelta(days=28),
        current_time,
    )
    month_to_date = summarize_period("Month to date", insights, month_start, current_time)
    year_to_date = summarize_period("Year to date", insights, year_start, current_time)

    notable_sessions = sorted(insights, key=lambda item: item.load_score, reverse=True)[:5]
    load_flags = build_load_flags(last_7_days, rolling_28_days, current_week, previous_week)

    return RenderContext(
        insights=insights,
        last_7_days=last_7_days,
        current_week=current_week,
        previous_week=previous_week,
        last_14_days=last_14_days,
        rolling_28_days=rolling_28_days,
        month_to_date=month_to_date,
        year_to_date=year_to_date,
        notable_sessions=notable_sessions,
        load_flags=load_flags,
    )


def summarize_period(
    label: str,
    insights: list[ActivityInsight],
    start: datetime,
    end: datetime,
) -> PeriodSummary:
    """Summarize a time range for reporting and Markdown rendering."""

    filtered = [
        insight
        for insight in insights
        if start <= insight.activity.start_date.astimezone(start.tzinfo) < end
    ]
    sport_breakdown: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "activity_count": 0,
            "distance_km": 0.0,
            "moving_time_hours": 0.0,
            "load": 0.0,
        }
    )
    zone_totals: dict[str, dict[int, dict[str, float | int | None]]] = defaultdict(dict)

    total_distance_km = 0.0
    total_moving_time_hours = 0.0
    total_elevation_gain_m = 0.0
    total_load = 0.0
    for insight in filtered:
        activity = insight.activity
        sport = activity.sport_type
        sport_breakdown[sport]["activity_count"] += 1
        sport_breakdown[sport]["distance_km"] += activity.distance_kilometers
        sport_breakdown[sport]["moving_time_hours"] += round(activity.moving_time_seconds / 3600.0, 2)
        sport_breakdown[sport]["load"] += insight.load_score

        total_distance_km += activity.distance_kilometers
        total_moving_time_hours += activity.moving_time_seconds / 3600.0
        total_elevation_gain_m += activity.total_elevation_gain_meters or 0.0
        total_load += insight.load_score

        for zone in activity.zones:
            slot = zone_totals[zone.resource].setdefault(
                zone.zone_index,
                {
                    "zone_index": zone.zone_index,
                    "min_value": zone.min_value,
                    "max_value": zone.max_value,
                    "time_seconds": 0,
                },
            )
            slot["time_seconds"] = int(slot["time_seconds"]) + zone.time_seconds

    normalized_zones = {
        resource: [zone for _, zone in sorted(items.items(), key=lambda item: item[0])]
        for resource, items in zone_totals.items()
    }

    return PeriodSummary(
        label=label,
        start=start,
        end=end,
        activity_count=len(filtered),
        total_distance_km=round(total_distance_km, 2),
        total_moving_time_hours=round(total_moving_time_hours, 2),
        total_elevation_gain_m=round(total_elevation_gain_m, 1),
        total_load=round(total_load, 2),
        sport_breakdown={
            sport: {
                key: round(value, 2) if isinstance(value, float) else value
                for key, value in metrics.items()
            }
            for sport, metrics in sorted(sport_breakdown.items())
        },
        zone_totals=normalized_zones,
        activities=filtered,
    )


def build_load_flags(
    last_7_days: PeriodSummary,
    rolling_28_days: PeriodSummary,
    current_week: PeriodSummary,
    previous_week: PeriodSummary,
) -> list[str]:
    """Build simple recovery and load-trend notes for the dashboard."""

    flags: list[str] = []
    if rolling_28_days.activity_count and last_7_days.total_load > rolling_28_days.total_load / 4 * 1.4:
        flags.append("Recent 7-day load is materially above the rolling 28-day average.")
    if previous_week.total_load and current_week.total_load > previous_week.total_load * 1.25:
        flags.append("Current week load is trending higher than the previous week.")
    if last_7_days.activity_count == 0:
        flags.append("No activities were recorded in the last 7 days.")
    return flags
