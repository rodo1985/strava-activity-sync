"""Exporters for writing rendered artifacts to external destinations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from strava_activity_sync.config import Settings


@dataclass(slots=True)
class RenderedFile:
    """Single rendered output file ready for export."""

    relative_path: Path
    content: str


@dataclass(slots=True)
class ExportBundle:
    """Collection of files produced by the renderer."""

    files: list[RenderedFile]


class Exporter(ABC):
    """Abstract exporter used by the render service."""

    @abstractmethod
    def export(self, bundle: ExportBundle) -> list[Path]:
        """Export a bundle of rendered files."""


class LocalFilesystemExporter(Exporter):
    """Exporter that writes files into the configured local export directory."""

    def __init__(self, export_directory: Path) -> None:
        self.export_directory = export_directory

    def export(self, bundle: ExportBundle) -> list[Path]:
        """Write rendered files to disk and return their absolute paths."""

        written_paths: list[Path] = []
        self.export_directory.mkdir(parents=True, exist_ok=True)
        for rendered_file in bundle.files:
            target = self.export_directory / rendered_file.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered_file.content, encoding="utf-8")
            written_paths.append(target.resolve())
        return written_paths


class GoogleDriveExporter(Exporter):
    """Placeholder exporter for a future Google Drive integration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def export(self, bundle: ExportBundle) -> list[Path]:
        """Raise until the Google Drive integration is intentionally implemented."""

        raise NotImplementedError(
            "Google Drive export is intentionally disabled in v1. "
            "Set ENABLE_DRIVE_EXPORT=false and use the local filesystem exporter."
        )

