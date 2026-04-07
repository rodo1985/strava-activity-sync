"""Tests for Vercel Blob-backed storage and export helpers."""

from __future__ import annotations

import json
from pathlib import Path

from strava_activity_sync.services.exporters import ExportBundle, RenderedFile, VercelBlobExporter
from strava_activity_sync.services.sync_service import build_activity_record
from strava_activity_sync.storage.blob_repository import VercelBlobStravaRepository

from conftest import load_fixture


class FakeBlobResult:
    """Tiny fake blob response object returned by the fake blob client."""

    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


class FakeBlobClient:
    """Simple in-memory blob client used to test Vercel Blob helpers."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, path: str, body: bytes, **_: object) -> dict[str, str]:
        """Store one blob object by pathname."""

        self.objects[path] = body
        return {"pathname": path}

    def get(self, path: str, **_: object) -> FakeBlobResult | None:
        """Return one stored blob object when present."""

        if path not in self.objects:
            return None
        return FakeBlobResult(self.objects[path])

    def delete(self, url_or_path) -> None:
        """Delete one or more stored blob paths."""

        if isinstance(url_or_path, str):
            paths = [url_or_path]
        else:
            paths = list(url_or_path)
        for path in paths:
            self.objects.pop(path, None)


def test_vercel_blob_repository_round_trip(monkeypatch, settings) -> None:
    """The blob repository should persist and reload Strava activity state."""

    fake_blob_client = FakeBlobClient()
    monkeypatch.setattr(
        "strava_activity_sync.storage.blob_repository.BlobClient",
        lambda *args, **kwargs: fake_blob_client,
    )
    settings.storage_backend = "vercel_blob"

    repository = VercelBlobStravaRepository(settings)
    activity = build_activity_record(
        load_fixture("activity_detail.json"),
        load_fixture("zones.json"),
        load_fixture("laps.json"),
        load_fixture("streams.json"),
    )

    repository.upsert_activity_bundle(activity)
    repository.set_sync_state("reconciliation", {"phase": "recent"})

    loaded_activities = repository.list_activities()
    assert len(loaded_activities) == 1
    assert loaded_activities[0].activity_id == activity.activity_id
    assert repository.activity_exists(activity.activity_id) is True
    assert repository.get_sync_state("reconciliation") == {"phase": "recent"}


def test_vercel_blob_exporter_writes_manifest(monkeypatch, settings) -> None:
    """The Vercel Blob exporter should publish files and a manifest."""

    fake_blob_client = FakeBlobClient()
    monkeypatch.setattr(
        "strava_activity_sync.services.exporters.BlobClient",
        lambda *args, **kwargs: fake_blob_client,
    )
    settings.export_backend = "vercel_blob"

    exporter = VercelBlobExporter(settings)
    bundle = ExportBundle(
        files=[
            RenderedFile(Path("dashboard.md"), "# Dashboard\n"),
            RenderedFile(Path("dashboard.json"), "{}\n"),
        ]
    )

    written_paths = exporter.export(bundle)
    manifest_path = f"{settings.vercel_blob_export_prefix.rstrip('/')}/_manifest.json"
    manifest = json.loads(fake_blob_client.objects[manifest_path].decode("utf-8"))

    assert str(written_paths[0]).endswith("dashboard.md")
    assert manifest["paths"] == [
        f"{settings.vercel_blob_export_prefix.rstrip('/')}/dashboard.md",
        f"{settings.vercel_blob_export_prefix.rstrip('/')}/dashboard.json",
    ]
