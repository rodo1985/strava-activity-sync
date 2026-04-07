"""Vercel entrypoint exposing the FastAPI application under `/api`."""

from __future__ import annotations

import sys
from pathlib import Path


# Vercel executes the function from the repository root, so make the `src`
# layout explicit before importing the packaged application module.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from strava_activity_sync.app import app
