"""Exporters for writing rendered artifacts to external destinations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path

from vercel.blob import BlobClient

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

    @abstractmethod
    def clean(self) -> None:
        """Remove previously exported files from the destination."""


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

    def clean(self) -> None:
        """Remove all previously exported files from the local export directory.

        Returns:
            None: The export directory is deleted and recreated when it exists.
        """

        if self.export_directory.exists():
            for path in sorted(self.export_directory.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
        self.export_directory.mkdir(parents=True, exist_ok=True)


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


class VercelBlobExporter(Exporter):
    """Exporter that writes rendered artifacts into a private Vercel Blob store."""

    def __init__(self, settings: Settings) -> None:
        """Create the blob-backed exporter.

        Parameters:
            settings: Application settings providing blob prefix and access mode.
        """

        self.settings = settings
        self.client = BlobClient()

    def export(self, bundle: ExportBundle) -> list[Path]:
        """Write rendered files to Vercel Blob and return logical artifact paths."""

        previous_manifest = self._read_manifest()
        current_paths: list[str] = []
        for rendered_file in bundle.files:
            blob_path = self._blob_path_for(rendered_file.relative_path)
            self.client.put(
                blob_path,
                rendered_file.content.encode("utf-8"),
                access=self.settings.vercel_blob_access,
                content_type=self._guess_content_type(rendered_file.relative_path),
                overwrite=True,
            )
            current_paths.append(blob_path)

        stale_paths = sorted(set(previous_manifest) - set(current_paths))
        if stale_paths:
            self.client.delete(stale_paths)

        self.client.put(
            self._manifest_path(),
            json.dumps({"paths": current_paths}, indent=2, sort_keys=True).encode("utf-8"),
            access=self.settings.vercel_blob_access,
            content_type="application/json",
            overwrite=True,
        )

        return [Path(path) for path in current_paths]

    def clean(self) -> None:
        """Delete the currently tracked blob exports and reset the manifest."""

        manifest_paths = self._read_manifest()
        if manifest_paths:
            self.client.delete(manifest_paths)
        self.client.delete(self._manifest_path())

    def _read_manifest(self) -> list[str]:
        """Load the current export manifest when one has been published.

        Returns:
            list[str]: Blob paths previously written by this exporter.
        """

        result = self.client.get(self._manifest_path(), access=self.settings.vercel_blob_access)
        if result is None or result.status_code != 200:
            return []
        return json.loads(result.content.decode("utf-8")).get("paths", [])

    def _manifest_path(self) -> str:
        """Return the blob path used for the current export manifest."""

        return f"{self.settings.vercel_blob_export_prefix.rstrip('/')}/_manifest.json"

    def _blob_path_for(self, relative_path: Path) -> str:
        """Return the blob pathname for one rendered file."""

        prefix = self.settings.vercel_blob_export_prefix.rstrip("/")
        return f"{prefix}/{relative_path.as_posix()}"

    def _guess_content_type(self, relative_path: Path) -> str:
        """Infer the blob content type for one rendered artifact."""

        if relative_path.suffix == ".md":
            return "text/markdown; charset=utf-8"
        if relative_path.suffix == ".json":
            return "application/json"
        guessed_type, _ = mimetypes.guess_type(relative_path.name)
        return guessed_type or "application/octet-stream"

    def clean(self) -> None:
        """Raise until the Google Drive integration is intentionally implemented.

        Returns:
            None
        """

        raise NotImplementedError(
            "Google Drive export is intentionally disabled in v1. "
            "Set ENABLE_DRIVE_EXPORT=false and use the local filesystem exporter."
        )
