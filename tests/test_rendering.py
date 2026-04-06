"""Tests for deterministic Markdown and JSON rendering."""

import json

from strava_activity_sync.services.sync_service import build_activity_record

from conftest import load_fixture


def test_rendering_is_deterministic(render_service) -> None:
    """Rendering the same activities twice should produce identical output."""

    activities = [
        build_activity_record(
            load_fixture("activity_detail.json"),
            load_fixture("zones.json"),
            load_fixture("laps.json"),
            load_fixture("streams.json"),
        ),
        build_activity_record(
            load_fixture("activity_detail_second.json"),
            load_fixture("zones.json"),
            load_fixture("laps.json"),
            load_fixture("streams.json"),
        ),
    ]

    first_bundle = render_service.build_bundle(activities)
    second_bundle = render_service.build_bundle(activities)

    assert [(file.relative_path, file.content) for file in first_bundle.files] == [
        (file.relative_path, file.content) for file in second_bundle.files
    ]

    json_file = next(file for file in first_bundle.files if file.relative_path.name == "activity_index.json")
    parsed = json.loads(json_file.content)
    assert parsed[0]["activity_id"] in {12345, 67890}

    detail_file = next(file for file in first_bundle.files if file.relative_path.name.endswith(".md") and "activities/" in str(file.relative_path))
    assert "## Zones" in detail_file.content
    assert "### Heartrate Zone" in detail_file.content
    assert "### Power Zone" in detail_file.content


def test_clean_exports_removes_existing_files(render_service) -> None:
    """Cleaning exports should remove the current rendered files from disk."""

    activities = [
        build_activity_record(
            load_fixture("activity_detail.json"),
            load_fixture("zones.json"),
            load_fixture("laps.json"),
            load_fixture("streams.json"),
        )
    ]

    render_service.render_and_export(activities)
    assert any(render_service.exporter.export_directory.rglob("*"))

    render_service.clean_exports()

    remaining_paths = list(render_service.exporter.export_directory.rglob("*"))
    assert remaining_paths == []
