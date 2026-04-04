"""Module entrypoint for running the Typer CLI with ``python -m``."""

from strava_activity_sync.cli import app


def main() -> None:
    """Run the command-line application."""

    app()


if __name__ == "__main__":
    main()
