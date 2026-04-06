"""Rendering service for deterministic Markdown and JSON exports."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from strava_activity_sync.domain.load_metrics import (
    PeriodSummary,
    RenderContext,
    build_render_context,
)
from strava_activity_sync.domain.models import (
    ActivityInsight,
    ActivityLap,
    ActivityRecord,
    ActivityZone,
)
from strava_activity_sync.services.exporters import ExportBundle, Exporter, RenderedFile


class RenderService:
    """Render Markdown and JSON exports from stored activity records."""

    def __init__(self, exporter: Exporter, timezone_name: str) -> None:
        template_root = Path(__file__).resolve().parent.parent / "templates" / "markdown"
        self.environment = Environment(
            loader=FileSystemLoader(template_root),
            autoescape=select_autoescape(disabled_extensions=("md", "j2", "json")),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.exporter = exporter
        self.timezone_name = timezone_name

    def render_and_export(self, activities: list[ActivityRecord]) -> list[Path]:
        """Render all deterministic artifacts and export them via the configured exporter."""

        bundle = self.build_bundle(activities)
        return self.exporter.export(bundle)

    def clean_exports(self) -> None:
        """Remove the current exported artifact set from the configured exporter.

        Returns:
            None: Existing export files are removed from the destination.
        """

        self.exporter.clean()

    def build_bundle(self, activities: list[ActivityRecord]) -> ExportBundle:
        """Build the full export bundle without writing any files.

        Parameters:
            activities: Stored activity records that should be transformed into
                deterministic Strava context artifacts.

        Returns:
            ExportBundle: The full set of Markdown and JSON exports that should
                be written by the configured exporter.
        """

        context = build_render_context(activities, self.timezone_name)
        files = [
            RenderedFile(Path("dashboard.md"), self._render_markdown("dashboard.md.j2", context)),
            RenderedFile(Path("dashboard.json"), self._render_dashboard_json(context)),
            RenderedFile(
                Path("recent_activities.md"),
                self._render_markdown("recent_activities.md.j2", context),
            ),
            RenderedFile(
                Path("recent_activities.json"),
                self._render_recent_activities_json(context),
            ),
            RenderedFile(
                Path("training_load.md"),
                self._render_markdown("training_load.md.j2", context),
            ),
            RenderedFile(
                Path("training_load.json"),
                self._render_training_load_json(context),
            ),
            RenderedFile(Path("activity_index.json"), self._render_activity_index(context)),
        ]

        for insight in context.insights:
            files.append(
                RenderedFile(
                    self._detail_relative_path(insight),
                    self._render_markdown("activity_detail.md.j2", context, insight=insight),
                )
            )

        return ExportBundle(files=files)

    def _render_markdown(
        self,
        template_name: str,
        context: RenderContext,
        insight: ActivityInsight | None = None,
    ) -> str:
        """Render a single Markdown template using the shared context."""

        template = self.environment.get_template(template_name)
        rendered = template.render(
            context=context,
            insight=insight,
            detail_path_for=self._detail_relative_path,
            format_activity_zones=self._format_activity_zones,
        )
        return rendered.rstrip() + "\n"

    def _render_activity_index(self, context: RenderContext) -> str:
        """Render the machine-friendly activity index JSON file.

        Parameters:
            context: Derived render context for the current activity set.

        Returns:
            str: Pretty-printed JSON describing the exported activity index.
        """

        items = []
        for insight in context.insights:
            activity = insight.activity
            items.append(
                {
                    "activity_id": activity.activity_id,
                    "started_at": activity.start_date.isoformat(),
                    "sport_type": activity.sport_type,
                    "name": activity.name,
                    "distance_km": activity.distance_kilometers,
                    "moving_time_min": activity.moving_time_minutes,
                    "load_score": insight.load_score,
                    "load_source": insight.load_source,
                    "tags": insight.tags,
                    "detail_file": str(self._detail_relative_path(insight)),
                }
            )
        return json.dumps(items, indent=2, sort_keys=True) + "\n"

    def _render_dashboard_json(self, context: RenderContext) -> str:
        """Render the compact Strava dashboard JSON companion file.

        Parameters:
            context: Derived render context for the current activity set.

        Returns:
            str: Pretty-printed JSON dashboard payload for downstream services.
        """

        payload = {
            "generated_timezone": self.timezone_name,
            "last_7_days": self._serialize_period_summary(context.last_7_days),
            "current_week": self._serialize_period_summary(context.current_week),
            "previous_week": self._serialize_period_summary(context.previous_week),
            "month_to_date": self._serialize_period_summary(context.month_to_date),
            "year_to_date": self._serialize_period_summary(context.year_to_date),
            "notable_sessions": [
                self._serialize_activity_insight(insight) for insight in context.notable_sessions
            ],
            "load_flags": context.load_flags,
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _render_recent_activities_json(self, context: RenderContext) -> str:
        """Render the recent-activities JSON companion file.

        Parameters:
            context: Derived render context for the current activity set.

        Returns:
            str: Pretty-printed JSON for the recent activity window.
        """

        payload = {
            "generated_timezone": self.timezone_name,
            "window": self._serialize_period_summary(context.last_14_days),
            "activities": [
                self._serialize_activity_insight(insight) for insight in context.last_14_days.activities
            ],
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _render_training_load_json(self, context: RenderContext) -> str:
        """Render the training-load JSON companion file.

        Parameters:
            context: Derived render context for the current activity set.

        Returns:
            str: Pretty-printed JSON for load and zone summaries.
        """

        payload = {
            "generated_timezone": self.timezone_name,
            "rolling_7_days": self._serialize_period_summary(context.last_7_days),
            "rolling_28_days": self._serialize_period_summary(context.rolling_28_days),
            "current_week": self._serialize_period_summary(context.current_week),
            "previous_week": self._serialize_period_summary(context.previous_week),
            "month_to_date": self._serialize_period_summary(context.month_to_date),
            "year_to_date": self._serialize_period_summary(context.year_to_date),
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _serialize_period_summary(self, summary: PeriodSummary) -> dict[str, object]:
        """Convert a period summary into a stable JSON-friendly structure.

        Parameters:
            summary: Aggregated period summary built from deterministic analytics.

        Returns:
            dict[str, object]: JSON-serializable summary payload for the period.
        """

        return {
            "label": summary.label,
            "start": summary.start.isoformat(),
            "end": summary.end.isoformat(),
            "activity_count": summary.activity_count,
            "total_distance_km": summary.total_distance_km,
            "total_moving_time_hours": summary.total_moving_time_hours,
            "total_elevation_gain_m": summary.total_elevation_gain_m,
            "total_load": summary.total_load,
            "sport_breakdown": summary.sport_breakdown,
            "zone_totals": summary.zone_totals,
            # Keep the embedded activity list lightweight so the summary JSON
            # stays compact while still letting downstream services inspect
            # which activities contributed to the period totals.
            "activities": [self._serialize_activity_insight(insight) for insight in summary.activities],
        }

    def _serialize_activity_insight(self, insight: ActivityInsight) -> dict[str, object]:
        """Convert one derived activity insight into a JSON-friendly structure.

        Parameters:
            insight: Derived activity insight to serialize.

        Returns:
            dict[str, object]: JSON payload containing activity detail, tags,
                load information, and the exported detail file path.
        """

        activity = insight.activity
        return {
            "activity": self._serialize_activity(activity),
            "load_score": insight.load_score,
            "load_source": insight.load_source,
            "tags": insight.tags,
            "interval_summary": insight.interval_summary,
            "detail_file": str(self._detail_relative_path(insight)),
        }

    def _serialize_activity(self, activity: ActivityRecord) -> dict[str, object]:
        """Convert one stored activity into a JSON-friendly structure.

        Parameters:
            activity: Stored activity record to serialize.

        Returns:
            dict[str, object]: JSON payload containing the core activity facts,
                zones, laps, and available stream metadata.
        """

        return {
            "activity_id": activity.activity_id,
            "athlete_id": activity.athlete_id,
            "name": activity.name,
            "sport_type": activity.sport_type,
            "start_date": activity.start_date.isoformat(),
            "timezone": activity.timezone,
            "distance_meters": activity.distance_meters,
            "distance_km": activity.distance_kilometers,
            "moving_time_seconds": activity.moving_time_seconds,
            "moving_time_minutes": activity.moving_time_minutes,
            "elapsed_time_seconds": activity.elapsed_time_seconds,
            "elapsed_time_minutes": activity.elapsed_time_minutes,
            "total_elevation_gain_meters": activity.total_elevation_gain_meters,
            "average_speed_mps": activity.average_speed_mps,
            "max_speed_mps": activity.max_speed_mps,
            "average_heartrate": activity.average_heartrate,
            "max_heartrate": activity.max_heartrate,
            "average_watts": activity.average_watts,
            "weighted_average_watts": activity.weighted_average_watts,
            "kilojoules": activity.kilojoules,
            "suffer_score": activity.suffer_score,
            "trainer": activity.trainer,
            "commute": activity.commute,
            "manual": activity.manual,
            "is_private": activity.is_private,
            "deleted": activity.deleted,
            "zones": [self._serialize_activity_zone(zone) for zone in activity.zones],
            "laps": [self._serialize_activity_lap(lap) for lap in activity.laps],
            "available_streams": sorted(activity.streams.keys()),
        }

    def _serialize_activity_zone(self, zone: ActivityZone) -> dict[str, object]:
        """Convert one activity zone row into JSON-friendly output.

        Parameters:
            zone: Stored zone row to serialize.

        Returns:
            dict[str, object]: JSON payload for one time-in-zone record.
        """

        return {
            "resource": zone.resource,
            "zone_index": zone.zone_index,
            "min_value": zone.min_value,
            "max_value": zone.max_value,
            "time_seconds": zone.time_seconds,
        }

    def _serialize_activity_lap(self, lap: ActivityLap) -> dict[str, object]:
        """Convert one stored lap into JSON-friendly output.

        Parameters:
            lap: Stored activity lap to serialize.

        Returns:
            dict[str, object]: JSON payload for one lap row.
        """

        return {
            "lap_id": lap.lap_id,
            "lap_index": lap.lap_index,
            "name": lap.name,
            "elapsed_time_seconds": lap.elapsed_time_seconds,
            "moving_time_seconds": lap.moving_time_seconds,
            "distance_meters": lap.distance_meters,
            "average_speed_mps": lap.average_speed_mps,
            "average_heartrate": lap.average_heartrate,
            "max_heartrate": lap.max_heartrate,
            "average_watts": lap.average_watts,
            "pace_zone": lap.pace_zone,
            "split": lap.split,
        }

    def _detail_relative_path(self, insight: ActivityInsight) -> Path:
        """Return the stable relative path used for an activity detail file."""

        activity = insight.activity
        slug = activity.sport_type.lower().replace(" ", "_").replace("/", "_")
        date_part = activity.start_date.date().isoformat()
        return Path("activities") / str(activity.start_date.year) / (
            f"{date_part}--{slug}--{activity.activity_id}.md"
        )

    def _format_activity_zones(self, insight: ActivityInsight) -> str:
        """Return a stable Markdown block for grouped activity zone details.

        Parameters:
            insight: Activity insight containing the raw zone rows to render.

        Returns:
            str: Markdown body for the activity's zone section.
        """

        if not insight.activity.zones:
            return "- No zone data was available for this activity."

        grouped_zones: dict[str, list[ActivityZone]] = {
            "heartrate": [zone for zone in insight.activity.zones if zone.resource == "heartrate"],
            "power": [zone for zone in insight.activity.zones if zone.resource == "power"],
        }
        other_resources = sorted(
            {
                zone.resource
                for zone in insight.activity.zones
                if zone.resource not in {"heartrate", "power"}
            }
        )

        lines: list[str] = []
        if grouped_zones["heartrate"]:
            lines.append("### Heartrate Zone")
            lines.extend(self._format_zone_lines(grouped_zones["heartrate"]))

        if grouped_zones["power"]:
            if lines:
                lines.append("")
            lines.append("### Power Zone")
            lines.extend(self._format_zone_lines(grouped_zones["power"]))

        for resource in other_resources:
            resource_zones = [zone for zone in insight.activity.zones if zone.resource == resource]
            if lines:
                lines.append("")
            lines.append(f"### {resource.replace('_', ' ').title()} Zone")
            lines.extend(self._format_zone_lines(resource_zones))

        return "\n".join(lines)

    def _format_zone_lines(self, zones: list[ActivityZone]) -> list[str]:
        """Format a set of same-resource zones as bullet lines.

        Parameters:
            zones: Zone rows sharing the same Strava resource type.

        Returns:
            list[str]: Markdown bullet lines for each zone.
        """

        return [self._format_zone_line(zone) for zone in zones]

    def _format_zone_line(self, zone: ActivityZone) -> str:
        """Format one zone row as a Markdown bullet line.

        Parameters:
            zone: Zone row that should be presented in Markdown.

        Returns:
            str: One Markdown bullet line describing the zone duration and
                configured min/max bounds.
        """

        line = f"- {zone.resource} zone {zone.zone_index}: {zone.time_seconds} seconds"
        if zone.min_value is not None:
            line += f", min {zone.min_value}"
        if zone.max_value is not None:
            line += f", max {zone.max_value}"
        return line
