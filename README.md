# strava-activity-sync

`strava-activity-sync` is a Strava synchronization service for a single athlete that is now shaped for Vercel deployment. It ingests Strava activities, persists activity state through a pluggable storage backend, and deterministically generates Markdown and JSON artifacts for downstream tools and AI agents.

The project still supports simple local development, but the primary deployment target is now Vercel. It avoids LLMs in the sync and rendering pipeline and keeps artifact generation deterministic.

Supabase integration now has a first working runtime path for the existing APEX
schema. The service still keeps its canonical local mirror in SQLite or Vercel
Blob, but when APEX Supabase credentials are configured it can also project
synced activities into the current `daily_log` and `activities` tables.

## Key Features / Scope

- Sync Strava activities for a single athlete via OAuth.
- Use Strava webhooks as the primary trigger for create, update, and delete events.
- Run a bounded recent-first seed sync when the athlete first connects.
- Use Strava webhooks as the primary near-real-time update path.
- Use a Vercel cron endpoint for scheduled reconciliation.
- Grow older history gradually by pulling one historical summary page whenever the recent collector has nothing new to ingest.
- Store normalized activity detail through a pluggable repository backend:
  - SQLite for local development
  - Vercel Blob for Vercel deployments
- Generate deterministic exports:
  - `dashboard.md`
  - `dashboard.json`
  - `recent_activities.md`
  - `recent_activities.json`
  - `training_load.md`
  - `training_load.json`
  - `activity_index.json`
  - `activities/<year>/<date>--<sport>--<activity_id>.md`
- Provide CLI commands for backfill, reconciliation, render, and local serving.
- Include a Vercel entrypoint and `vercel.json` cron configuration.

Non-goals for v1:

- No frontend UI.
- No multi-athlete support.
- No AI-generated summaries.
- No Google Drive sync yet, though the exporter boundary is ready for it.
- No multi-user tenancy.
- No AI-generated summaries in the canonical export path.

## Setup

### Prerequisites

- Python `3.12`
- [uv](https://docs.astral.sh/uv/) installed locally
- A Strava developer application with OAuth and webhook settings
- A Vercel project if you plan to deploy this service
- A Vercel Blob store if you plan to use the Vercel deployment target
- A Supabase project if you want to validate the shared Postgres schema for the
  wider APEX system

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

### Supabase setup

The repository now includes the first Supabase integration step:

- the existing APEX schema remains your app-facing model
- the new Strava migration adds canonical `strava_*` tables beside it
- a SQL projection function maps canonical Strava rows back into the existing
  `activities` table

Where to put the secrets:

- local development: put them in `.env`
- Vercel: add them in the project Environment Variables settings
- never commit real values to git

Recommended Supabase variables:

```bash
APEX_SUPABASE_URL=
APEX_SUPABASE_SERVICE_ROLE_KEY=
APEX_SUPABASE_SCHEMA=public
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_SUPABASE_USER_ID=sergio
SUPABASE_DB_HOST=
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=
SUPABASE_DB_SSLMODE=require
SUPABASE_STORAGE_BUCKET=strava-context
```

Important note:

- the current Python service now consumes the `APEX_SUPABASE_*` variables for
  projection into the existing APEX schema
- canonical Strava storage still lives in SQLite locally and Vercel Blob in the
  hosted path
- the later migration to canonical `strava_*` tables in Supabase is still a
  follow-up step

Recommended naming convention:

- backend services: `APEX_SUPABASE_*`
- frontend apps: `VITE_SUPABASE_*`

That keeps this repo aligned with the rest of your APEX setup while still
leaving room for lower-level Postgres settings when needed.

### Strava app setup

Configure the Strava app with:

- Authorization callback domain and URI matching `STRAVA_REDIRECT_URI`
- Webhook callback URL matching `STRAVA_WEBHOOK_CALLBACK_URL`
- Requested scopes:
  - `read`
  - `activity:read_all`
  - `profile:read_all`

For a Vercel deployment, the callback and webhook URLs should point to the FastAPI function under `/api`, for example:

- `STRAVA_REDIRECT_URI=https://your-project.vercel.app/api/auth/strava/callback`
- `STRAVA_WEBHOOK_CALLBACK_URL=https://your-project.vercel.app/api/webhooks/strava`

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
uv run strava-sync backfill --days 30
```

Run the recent-first collector manually:

```bash
uv run strava-sync reconcile
```

Project locally stored activities into the current APEX Supabase schema:

```bash
uv run strava-sync project-apex
```

Project only the most recent 10 locally stored activities:

```bash
uv run strava-sync project-apex --limit 10
```

Regenerate all exports from local storage:

```bash
uv run strava-sync render
```

Remove all generated exports:

```bash
uv run strava-sync clean-exports
```

Clean the export directory and rebuild everything from SQLite:

```bash
uv run strava-sync rebuild-exports
```

Run the test suite:

```bash
uv run pytest
```

### Vercel deployment

1. Create a Vercel Blob store in the same project.
2. Add the project environment variables from `.env.template`.
3. Set these Vercel-specific values:

```bash
DEPLOYMENT_TARGET=vercel
STORAGE_BACKEND=vercel_blob
EXPORT_BACKEND=vercel_blob
```

4. Set production callback URLs:

```bash
APP_BASE_URL=https://your-project.vercel.app/api
STRAVA_REDIRECT_URI=https://your-project.vercel.app/api/auth/strava/callback
STRAVA_WEBHOOK_CALLBACK_URL=https://your-project.vercel.app/api/webhooks/strava
```

5. Add a `CRON_SECRET` environment variable in Vercel.
6. Deploy the repo with Vercel.

This repo includes:

- `api/index.py` as the Vercel FastAPI entrypoint
- `vercel.json` with a scheduled reconcile job at `/api/cron/reconcile`

On Vercel, the app does not run APScheduler in-process. Scheduled reconciliation happens through the Vercel cron endpoint instead.

Important note:

- The included `vercel.json` uses a once-per-day reconcile schedule because that is compatible with Vercel Hobby projects.
- Strava webhooks should remain the primary freshness trigger.
- If you deploy on a Pro plan, you can increase the cron frequency by editing `vercel.json` and redeploying.

### Supabase validation workflow

If you want to validate the Supabase side right now, follow this order:

1. Create your Supabase project.
2. Run your base APEX schema in Supabase SQL Editor.
3. Run the Strava migration:

   [supabase/sql/2026-04-07_strava_integration.sql](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/supabase/sql/2026-04-07_strava_integration.sql)

4. Use the test steps in:

   [docs/supabase-strava-integration.md](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/supabase-strava-integration.md)

5. Start this service locally with valid Strava credentials and the
   `APEX_SUPABASE_*` variables filled in.
6. Run:

   ```bash
   uv run strava-sync project-apex
   ```

7. Confirm that:
   - `daily_log` rows exist for activity dates
   - `activities` rows were inserted or updated with Strava activity data
   - your current APEX app can read those projected activities normally

## Configuration

All configuration lives in environment variables. Copy `.env.template` to `.env` and set at least the following:

- `DEPLOYMENT_TARGET`
- `STORAGE_BACKEND`
- `EXPORT_BACKEND`
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_WEBHOOK_VERIFY_TOKEN`
- `STRAVA_WEBHOOK_CALLBACK_URL`
- `STRAVA_REDIRECT_URI`
- `CRON_SECRET`
- `APP_BASE_URL`
- `DATABASE_PATH`
- `EXPORT_DIR`
- `TIMEZONE`
- `SYNC_LOOKBACK_DAYS`
- `RECONCILIATION_INTERVAL_MINUTES`
- `RECONCILE_LOOKBACK_DAYS`
- `SYNC_BATCH_SIZE`
- `STRAVA_REQUEST_TIMEOUT_SECONDS`
- `STRAVA_VERIFY_SSL`
- `STRAVA_CA_BUNDLE_PATH`
- `VERCEL_BLOB_STATE_PATH`
- `VERCEL_BLOB_EXPORT_PREFIX`
- `VERCEL_BLOB_ACCESS`
- `APEX_SUPABASE_URL`
- `APEX_SUPABASE_SERVICE_ROLE_KEY`
- `APEX_SUPABASE_SCHEMA`
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_SUPABASE_USER_ID`
- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`
- `SUPABASE_DB_SSLMODE`
- `SUPABASE_STORAGE_BUCKET`

For Vercel Blob deployments, Vercel also needs to provide the Blob write token in the runtime environment:

- `BLOB_READ_WRITE_TOKEN`

Optional placeholders are included for a future Google Drive exporter:

- `ENABLE_DRIVE_EXPORT`
- `GOOGLE_DRIVE_FOLDER_ID`
- `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`

Secrets are never committed. Keep `.env` local and mount secrets through your deployment platform when self-hosting.

For Supabase:

- copy `APEX_SUPABASE_URL` from the project settings page
- copy `APEX_SUPABASE_SERVICE_ROLE_KEY` from API settings
- copy `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for frontend clients
- copy the Postgres host, user, password, and SSL requirements from the
  database connection settings
- keep `APEX_SUPABASE_SERVICE_ROLE_KEY` server-side only

Default deployment behavior:

- `DEPLOYMENT_TARGET=local` keeps the original local process behavior.
- `DEPLOYMENT_TARGET=vercel` disables in-process scheduler startup and expects scheduled reconciliation through `vercel.json`.
- `STORAGE_BACKEND=sqlite` stores Strava state in the local SQLite file.
- `STORAGE_BACKEND=vercel_blob` stores Strava state in a private Vercel Blob object.
- `EXPORT_BACKEND=local` writes rendered artifacts to the local filesystem.
- `EXPORT_BACKEND=vercel_blob` publishes rendered artifacts into the configured Vercel Blob prefix.
- `SYNC_LOOKBACK_DAYS=30` defines the trailing window used by startup sync and first-run seeding.
- `RECONCILIATION_INTERVAL_MINUTES=16` is still used by the local scheduler, but Vercel cron is configured separately through `vercel.json`.
- `RECONCILE_LOOKBACK_DAYS=14` defines the recent window inspected before falling back to older history.
- `SYNC_BATCH_SIZE=32` caps how many unknown activities a batch will fully hydrate.
- Startup, manual backfill, and scheduled collection skip streams by default to stay under Strava read limits. Webhook-driven sync still fetches streams.
- `STRAVA_VERIFY_SSL=true` keeps HTTPS verification enabled.
- `STRAVA_CA_BUNDLE_PATH` can point to a custom PEM bundle in the runtime environment when Strava traffic is intercepted by an enterprise or local TLS proxy.
- `/health` includes `last_sync_at`, `last_sync_phase`, and `last_startup_sync_at` so you can confirm webhook and scheduled sync activity.

## Project Structure

```text
.
├─ api/
│  └─ index.py
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
└─ pyproject.toml
└─ vercel.json
```

## Related Documentation

- [Architecture](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/architecture.md)
- [Shared Context Architecture](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/shared-context.md)
- [Strava Shared Context Contract](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/strava-context.md)
- [Supabase Strava Integration](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/supabase-strava-integration.md)
- [Strava Setup](/Users/REDONSX1/Documents/code/01 personal/strava-activity-sync/docs/strava-setup.md)

## Development Notes

- The rendering pipeline is deterministic by design. Do not add LLM calls to core sync or export generation.
- Treat webhook events as hints. Always re-fetch the detailed activity before updating the local store.
- SQLite is the local-development source of truth. Vercel Blob is the production-friendly serverless storage backend. Markdown and JSON files are generated artifacts.
- Supabase projection to the current APEX schema is now implemented. Canonical
  Strava storage in Supabase is still a follow-up refactor.
- Startup and scheduled batch sync intentionally skip Strava streams to stay under the tighter read limits. Webhook-driven sync still fetches streams for richer activity detail.
- The scheduler is recent-first: it checks the most recent trailing window first, then backfills one older page only when recent activity is already up to date.
- Vercel deployments do not run the in-process scheduler. Use webhooks plus the cron endpoint defined in `vercel.json`.
- Keep functions small, documented, and testable. This repo expects docstrings on all functions and classes.
- Prefer fixture-driven tests. Do not rely on live Strava calls in CI or unit tests.

## Contributing / Safe Changes

- Add or update tests for behavior changes.
- Update `README.md` and `docs/architecture.md` when setup, behavior, or output contracts change.
- Keep output formats stable unless there is a deliberate contract change for downstream consumers.
- When adding new exporters, do not couple them directly to sync logic. Extend the exporter boundary instead.
