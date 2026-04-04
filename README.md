# strava-activity-sync

`strava-activity-sync` is a local-first Python service that ingests Strava activities for a single athlete, stores normalized activity detail in SQLite, and deterministically generates Markdown and JSON artifacts for downstream tools and AI agents.

The project is designed for simple self-hosted environments such as a Raspberry Pi, Synology NAS, or small VM. It prefers clarity and portability over platform-specific infrastructure, and it avoids LLMs in the sync and rendering pipeline.

## Key Features / Scope

- Sync Strava activities for a single athlete via OAuth.
- Use Strava webhooks as the primary trigger for create, update, and delete events.
- Run scheduled reconciliation to catch missed webhook events and support local-only setups.
- Backfill the last 365 days on first startup when the local DB is empty.
- Store normalized activity detail in SQLite, including activity zones, laps, streams, and raw payloads.
- Generate deterministic exports:
  - `dashboard.md`
  - `recent_activities.md`
  - `training_load.md`
  - `activity_index.json`
  - `activities/<year>/<date>--<sport>--<activity_id>.md`
- Provide CLI commands for backfill, reconciliation, render, and local serving.

Non-goals for v1:

- No frontend UI.
- No multi-athlete support.
- No AI-generated summaries.
- No Google Drive sync yet, though the exporter boundary is ready for it.
- No Supabase or hosted database dependency.

## Setup

### Prerequisites

- Python `3.12`
- [uv](https://docs.astral.sh/uv/) installed locally
- A Strava developer application with OAuth and webhook settings

### uv setup

1. Create the virtual environment:

   ```bash
   uv venv
   ```

2. Sync dependencies:

   ```bash
   uv sync --group dev
   ```

3. Copy the environment template and fill in your Strava credentials:

   ```bash
   cp .env.template .env
   ```

4. Start the app locally:

   ```bash
   uv run uvicorn strava_activity_sync.app:app --host 0.0.0.0 --port 8000
   ```

### Strava app setup

Configure the Strava app with:

- Authorization callback domain and URI matching `STRAVA_REDIRECT_URI`
- Webhook callback URL matching `STRAVA_WEBHOOK_CALLBACK_URL`
- Requested scopes:
  - `read`
  - `activity:read_all`
  - `profile:read_all`

If you are running fully locally, you can still use the app without webhook delivery. In that case, rely on the reconciliation scheduler and manual CLI commands until you expose the service through a tunnel or reverse proxy.

For a step-by-step guide to obtaining `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_WEBHOOK_VERIFY_TOKEN`, and `STRAVA_WEBHOOK_CALLBACK_URL`, see [docs/strava-setup.md](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/strava-setup.md).

## How to Run

### Local development

Start the API server:

```bash
uv run uvicorn strava_activity_sync.app:app --host 0.0.0.0 --port 8000
```

Start the API server through the CLI:

```bash
uv run strava-sync serve --host 0.0.0.0 --port 8000
```

Run a one-time backfill:

```bash
uv run strava-sync backfill --days 365
```

Run scheduled reconciliation manually:

```bash
uv run strava-sync reconcile
```

Regenerate all exports from local storage:

```bash
uv run strava-sync render
```

Run the test suite:

```bash
uv run pytest
```

### Docker

Build and start the container:

```bash
docker compose up --build
```

The container stores SQLite data and rendered exports in mounted volumes:

- `./data/db`
- `./data/exports`

## Configuration

All configuration lives in environment variables. Copy `.env.template` to `.env` and set at least the following:

- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_WEBHOOK_VERIFY_TOKEN`
- `STRAVA_WEBHOOK_CALLBACK_URL`
- `STRAVA_REDIRECT_URI`
- `APP_BASE_URL`
- `DATABASE_PATH`
- `EXPORT_DIR`
- `TIMEZONE`
- `SYNC_LOOKBACK_DAYS`
- `RECONCILIATION_INTERVAL_MINUTES`
- `RECONCILE_LOOKBACK_DAYS`
- `STRAVA_REQUEST_TIMEOUT_SECONDS`

Optional placeholders are included for a future Google Drive exporter:

- `ENABLE_DRIVE_EXPORT`
- `GOOGLE_DRIVE_FOLDER_ID`
- `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`

Secrets are never committed. Keep `.env` local and mount secrets through your deployment platform when self-hosting.

## Project Structure

```text
.
├─ docs/
│  └─ architecture.md
├─ src/strava_activity_sync/
│  ├─ api/
│  ├─ domain/
│  ├─ scheduler/
│  ├─ services/
│  ├─ storage/
│  ├─ templates/markdown/
│  ├─ app.py
│  ├─ cli.py
│  ├─ config.py
│  └─ logging.py
├─ tests/
│  └─ fixtures/
├─ .env.template
├─ AGENTS.md
├─ Dockerfile
├─ docker-compose.yml
└─ pyproject.toml
```

## Development Notes

- The rendering pipeline is deterministic by design. Do not add LLM calls to core sync or export generation.
- Treat webhook events as hints. Always re-fetch the detailed activity before updating the local store.
- SQLite is the source of truth. Markdown and JSON files are generated artifacts.
- Keep functions small, documented, and testable. This repo expects docstrings on all functions and classes.
- Prefer fixture-driven tests. Do not rely on live Strava calls in CI or unit tests.

## Contributing / Safe Changes

- Add or update tests for behavior changes.
- Update `README.md` and `docs/architecture.md` when setup, behavior, or output contracts change.
- Keep output formats stable unless there is a deliberate contract change for downstream consumers.
- When adding new exporters, do not couple them directly to sync logic. Extend the exporter boundary instead.
