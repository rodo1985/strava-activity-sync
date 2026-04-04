"""Typer command-line entrypoint for manual sync and render workflows."""

from __future__ import annotations

import json

import typer
import uvicorn

from strava_activity_sync.app import build_services
from strava_activity_sync.config import get_settings


app = typer.Typer(help="Deterministic Strava activity sync and render commands.")


def main() -> None:
    """Run the Typer application.

    Returns:
        None: The process exits through Typer after command execution.
    """

    app()


@app.command()
def backfill(days: int = typer.Option(30, min=1, help="Trailing-window days to inspect for backfill.")) -> None:
    """Backfill a bounded batch of activities from the requested trailing window.

    Parameters:
        days: Number of trailing days to inspect for unknown activities.

    Returns:
        None: Prints a JSON summary to stdout.
    """

    services = build_services()
    result = services.backfill_service.backfill_days(days)
    typer.echo(json.dumps(result.__dict__, indent=2))


@app.command()
def reconcile(lookback_days: int = typer.Option(14, min=1, help="Recent-window days for scheduled collection.")) -> None:
    """Run the recent-first collector and print the resulting summary.

    Parameters:
        lookback_days: Number of trailing days to inspect before historical fallback.

    Returns:
        None: Prints a JSON summary to stdout.
    """

    services = build_services()
    result = services.sync_service.reconcile(lookback_days=lookback_days)
    typer.echo(json.dumps(result.__dict__, indent=2))


@app.command()
def render() -> None:
    """Render Markdown and JSON artifacts from the local SQLite database.

    Returns:
        None: Prints exported paths to stdout.
    """

    services = build_services()
    paths = services.sync_service.render_exports()
    typer.echo(json.dumps({"exported_paths": paths}, indent=2))


@app.command()
def serve(
    host: str = typer.Option(None, help="Host interface to bind."),
    port: int = typer.Option(None, min=1, max=65535, help="Port to bind."),
) -> None:
    """Run the FastAPI application with Uvicorn.

    Parameters:
        host: Optional host override for the HTTP server.
        port: Optional port override for the HTTP server.

    Returns:
        None: The process runs the Uvicorn server until interrupted.
    """

    settings = get_settings()
    uvicorn.run(
        "strava_activity_sync.app:app",
        host=host or settings.app_host,
        port=port or settings.app_port,
        reload=False,
    )
