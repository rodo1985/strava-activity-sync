# AGENTS.md

## Purpose

This repo is a local-first Strava synchronization service for a single athlete. The application stores Strava activity data in SQLite and deterministically renders Markdown and JSON artifacts for downstream tools.

## Main Rules

- Keep the sync and rendering path deterministic.
- Do not introduce AI or LLM calls into the core pipeline.
- SQLite is the source of truth.
- Markdown and JSON files are generated artifacts.
- Every function, method, and class must have a docstring.
- Add inline comments for non-obvious logic and tradeoffs.

## Module Boundaries

- `src/strava_activity_sync/api`: FastAPI routes for health, OAuth, and webhook intake.
- `src/strava_activity_sync/services/strava_client.py`: Strava HTTP and OAuth client.
- `src/strava_activity_sync/services/sync_service.py`: Activity sync orchestration.
- `src/strava_activity_sync/services/backfill_service.py`: First-run and manual backfill entrypoints.
- `src/strava_activity_sync/services/render_service.py`: Deterministic Markdown and JSON rendering.
- `src/strava_activity_sync/services/exporters.py`: Export backends.
- `src/strava_activity_sync/domain`: Shared models and analytics logic.
- `src/strava_activity_sync/storage`: SQLite schema and repositories.
- `src/strava_activity_sync/scheduler`: APScheduler integration.
- `tests`: Fixture-driven unit tests only.

## Standard Commands

- `uv venv`
- `uv sync --group dev`
- `uv run pytest`
- `uv run uvicorn strava_activity_sync.app:app --host 0.0.0.0 --port 8000`
- `uv run strava-sync backfill --days 365`
- `uv run strava-sync reconcile`
- `uv run strava-sync render`

## File Ownership Guidance

When parallelizing work, prefer this split:

- Docs and infrastructure: `README.md`, `docs/architecture.md`, `Dockerfile`, `docker-compose.yml`, `.env.template`, `pyproject.toml`
- Ingestion and storage: `api`, `storage`, `scheduler`, `strava_client`, `sync_service`, `backfill_service`, `app.py`, `cli.py`
- Analytics and rendering: `domain`, `render_service`, `exporters`, `templates/markdown`
- Tests and fixtures: `tests`

## Deterministic Rendering Rule

Generated exports must be derived from stored data using code and templates only. If future work adds a narrative or coaching layer, it must be optional and separate from the canonical artifact generation path.
