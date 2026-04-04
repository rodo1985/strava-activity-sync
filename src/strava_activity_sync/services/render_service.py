"""Rendering service for deterministic Markdown and JSON exports."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from strava_activity_sync.domain.load_metrics import RenderContext, build_render_context
from strava_activity_sync.domain.models import ActivityInsight, ActivityRecord
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

