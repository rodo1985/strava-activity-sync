"""Logging helpers for the Strava activity sync service."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once for the process.

    Parameters
    ----------
    level:
        Logging level string such as ``INFO`` or ``DEBUG``.

    Returns
    -------
    None
    """

    if logging.getLogger().handlers:
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
