"""SQLite helpers for initializing and accessing the application database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS athlete_profile (
    athlete_id INTEGER PRIMARY KEY,
    username TEXT,
    firstname TEXT,
    lastname TEXT,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    athlete_id INTEGER PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    scope TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id INTEGER PRIMARY KEY,
    athlete_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sport_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    timezone TEXT,
    distance_meters REAL NOT NULL,
    moving_time_seconds INTEGER NOT NULL,
    elapsed_time_seconds INTEGER NOT NULL,
    total_elevation_gain_meters REAL,
    average_speed_mps REAL,
    max_speed_mps REAL,
    average_heartrate REAL,
    max_heartrate REAL,
    average_watts REAL,
    weighted_average_watts REAL,
    kilojoules REAL,
    suffer_score REAL,
    trainer INTEGER NOT NULL DEFAULT 0,
    commute INTEGER NOT NULL DEFAULT 0,
    manual INTEGER NOT NULL DEFAULT 0,
    is_private INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_zones (
    activity_id INTEGER NOT NULL,
    resource TEXT NOT NULL,
    zone_index INTEGER NOT NULL,
    min_value REAL,
    max_value REAL,
    time_seconds INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (activity_id, resource, zone_index)
);

CREATE TABLE IF NOT EXISTS activity_laps (
    lap_id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL,
    lap_index INTEGER NOT NULL,
    name TEXT,
    elapsed_time_seconds INTEGER NOT NULL,
    moving_time_seconds INTEGER NOT NULL,
    distance_meters REAL NOT NULL,
    average_speed_mps REAL,
    average_heartrate REAL,
    max_heartrate REAL,
    average_watts REAL,
    pace_zone INTEGER,
    split INTEGER,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_streams (
    activity_id INTEGER NOT NULL,
    stream_key TEXT NOT NULL,
    data_json TEXT NOT NULL,
    series_type TEXT,
    original_size INTEGER,
    resolution TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (activity_id, stream_key)
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_json TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    outcome TEXT NOT NULL
);
"""


class Database:
    """Thin SQLite database wrapper used by repositories."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        """Create the database and ensure the schema exists."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection configured for row access by column name."""

        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

