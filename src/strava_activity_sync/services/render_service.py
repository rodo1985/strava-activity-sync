"""Rendering service for deterministic Markdown and JSON exports."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from strava_activity_sync.domain.load_metrics import RenderContext, build_render_context
from strava_activity_sync.domain.models import ActivityInsight, ActivityRecord, ActivityZone
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
        """Build the full export bundle without writing any files."""

        context = build_render_context(activities, self.timezone_name)
        files = [
            RenderedFile(Path("dashboard.md"), self._render_markdown("dashboard.md.j2", context)),
            RenderedFile(
                Path("recent_activities.md"),
                self._render_markdown("recent_activities.md.j2", context),
            ),
            RenderedFile(
                Path("training_load.md"),
                self._render_markdown("training_load.md.j2", context),
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
        """Render the machine-friendly activity index JSON file."""

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

        lines: list[str] = []
        for zone in zones:
            line = f"- {zone.resource} zone {zone.zone_index}: {zone.time_seconds} seconds"
            if zone.min_value is not None:
                line += f", min {zone.min_value}"
            if zone.max_value is not None:
                line += f", max {zone.max_value}"
            lines.append(line)
        return lines
