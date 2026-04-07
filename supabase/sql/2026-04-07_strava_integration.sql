-- ============================================================
--  APEX Daily Log — Strava Integration Layer
--  Run this after the base APEX schema in Supabase SQL Editor
-- ============================================================

-- Purpose:
-- - Keep canonical Strava data in dedicated strava_* tables
-- - Project synced Strava workouts into the existing `activities` table
-- - Preserve the existing daily_log / meals / food_items / daily_totals model

-- ============================================================
-- 0. EXTENSIONS
-- ============================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ============================================================
-- 1. MINIMAL EVOLUTION OF THE EXISTING ACTIVITIES TABLE
-- ============================================================
-- Keep the current APEX-facing `activities` table, but add source metadata so
-- it can safely contain both manual activities and Strava-projected activities.

ALTER TABLE activities
  ADD COLUMN IF NOT EXISTS user_id text NOT NULL DEFAULT 'sergio',
  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'manual'
    CHECK (source IN ('manual', 'strava')),
  ADD COLUMN IF NOT EXISTS external_id text,
  ADD COLUMN IF NOT EXISTS started_at timestamptz,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS raw_source jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'activities_user_id_fkey'
  ) THEN
    ALTER TABLE activities
      ADD CONSTRAINT activities_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES profile(user_id);
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'uq_activities_source_external_id'
  ) THEN
    ALTER TABLE activities
      ADD CONSTRAINT uq_activities_source_external_id UNIQUE (source, external_id);
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_activities_user_date
  ON activities (user_id, started_at DESC);


-- ============================================================
-- 2. STRAVA TOKENS
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_oauth_tokens (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         text NOT NULL DEFAULT 'sergio' UNIQUE
                  REFERENCES profile(user_id) ON DELETE CASCADE,
  athlete_id      bigint NOT NULL UNIQUE,
  access_token    text NOT NULL,
  refresh_token   text NOT NULL,
  expires_at      timestamptz NOT NULL,
  scope           text NOT NULL,
  raw_payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);


-- ============================================================
-- 3. STRAVA SYNC STATE
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_sync_state (
  user_id         text NOT NULL DEFAULT 'sergio'
                  REFERENCES profile(user_id) ON DELETE CASCADE,
  state_key       text NOT NULL,
  value_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, state_key)
);


-- ============================================================
-- 4. STRAVA WEBHOOK AUDIT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_webhook_events (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         text NOT NULL DEFAULT 'sergio'
                  REFERENCES profile(user_id) ON DELETE CASCADE,
  aspect_type     text,
  object_type     text,
  object_id       bigint,
  event_time      timestamptz,
  outcome         text NOT NULL,
  payload_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_strava_webhook_events_created_at
  ON strava_webhook_events (created_at DESC);


-- ============================================================
-- 5. CANONICAL STRAVA ACTIVITIES
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_activities (
  id                           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                      text NOT NULL DEFAULT 'sergio'
                               REFERENCES profile(user_id) ON DELETE CASCADE,
  strava_activity_id           bigint NOT NULL UNIQUE,
  athlete_id                   bigint NOT NULL,
  projected_activity_id        uuid REFERENCES activities(id) ON DELETE SET NULL,
  projected_daily_log_id       uuid REFERENCES daily_log(id) ON DELETE SET NULL,
  name                         text NOT NULL,
  sport_type                   text NOT NULL,
  started_at                   timestamptz NOT NULL,
  timezone                     text,
  distance_meters              numeric(12,2) NOT NULL DEFAULT 0,
  moving_time_seconds          integer NOT NULL DEFAULT 0,
  elapsed_time_seconds         integer NOT NULL DEFAULT 0,
  total_elevation_gain_meters  numeric(12,2),
  average_speed_mps            numeric(10,4),
  max_speed_mps                numeric(10,4),
  average_heartrate            numeric(8,2),
  max_heartrate                numeric(8,2),
  average_watts                numeric(10,2),
  weighted_average_watts       numeric(10,2),
  kilojoules                   numeric(12,2),
  suffer_score                 numeric(10,2),
  trainer                      boolean NOT NULL DEFAULT false,
  commute                      boolean NOT NULL DEFAULT false,
  manual                       boolean NOT NULL DEFAULT false,
  is_private                   boolean NOT NULL DEFAULT false,
  deleted                      boolean NOT NULL DEFAULT false,
  sync_status                  text NOT NULL DEFAULT 'synced'
                               CHECK (sync_status IN ('synced', 'deleted', 'error')),
  raw_payload                  jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at                   timestamptz NOT NULL DEFAULT now(),
  updated_at                   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_strava_activities_user_started_at
  ON strava_activities (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_strava_activities_projected_activity
  ON strava_activities (projected_activity_id);

CREATE INDEX IF NOT EXISTS idx_strava_activities_projected_daily_log
  ON strava_activities (projected_daily_log_id);


-- ============================================================
-- 6. ACTIVITY ZONES
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_activity_zones (
  strava_activity_id uuid NOT NULL
                     REFERENCES strava_activities(id) ON DELETE CASCADE,
  resource           text NOT NULL,
  zone_index         integer NOT NULL,
  min_value          numeric(10,2),
  max_value          numeric(10,2),
  time_seconds       integer NOT NULL DEFAULT 0,
  raw_payload        jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (strava_activity_id, resource, zone_index)
);


-- ============================================================
-- 7. ACTIVITY LAPS
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_activity_laps (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strava_activity_id  uuid NOT NULL REFERENCES strava_activities(id) ON DELETE CASCADE,
  strava_lap_id       bigint,
  lap_index           integer NOT NULL,
  name                text,
  elapsed_time_seconds integer NOT NULL DEFAULT 0,
  moving_time_seconds integer NOT NULL DEFAULT 0,
  distance_meters     numeric(12,2) NOT NULL DEFAULT 0,
  average_speed_mps   numeric(10,4),
  average_heartrate   numeric(8,2),
  max_heartrate       numeric(8,2),
  average_watts       numeric(10,2),
  pace_zone           integer,
  split               integer,
  raw_payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (strava_activity_id, lap_index)
);


-- ============================================================
-- 8. ACTIVITY STREAMS
-- ============================================================
CREATE TABLE IF NOT EXISTS strava_activity_streams (
  strava_activity_id  uuid NOT NULL REFERENCES strava_activities(id) ON DELETE CASCADE,
  stream_key          text NOT NULL,
  data_json           jsonb NOT NULL DEFAULT '[]'::jsonb,
  series_type         text,
  original_size       integer,
  resolution          text,
  raw_payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (strava_activity_id, stream_key)
);


-- ============================================================
-- 9. HELPER: MAP STRAVA SPORT -> APEX SPORT
-- ============================================================
CREATE OR REPLACE FUNCTION map_strava_sport_to_apex_sport(p_sport_type text)
RETURNS text AS $$
BEGIN
  RETURN CASE lower(coalesce(p_sport_type, ''))
    WHEN 'ride' THEN 'cycling'
    WHEN 'gravelride' THEN 'cycling'
    WHEN 'virtualride' THEN 'cycling'
    WHEN 'ebikeride' THEN 'cycling'
    WHEN 'run' THEN 'running'
    WHEN 'trailrun' THEN 'running'
    WHEN 'walk' THEN 'walking'
    WHEN 'hike' THEN 'hiking'
    WHEN 'swim' THEN 'swimming'
    WHEN 'weightsession' THEN 'strength'
    WHEN 'weighttraining' THEN 'strength'
    WHEN 'workout' THEN 'strength'
    ELSE 'default'
  END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================
-- 10. HELPER: PROJECT STRAVA ACTIVITY INTO APEX ACTIVITIES
-- ============================================================
-- This function keeps the existing APEX-facing `activities` table in sync with
-- the canonical `strava_activities` record.
--
-- Use cases:
-- - after every Strava activity upsert
-- - after a historical backfill
-- - after a Strava delete/update event
--
-- Notes:
-- - `p_day_type` lets your app choose the training day classification when it
--   creates a missing daily_log row.
-- - the function updates `strava_activities.projected_activity_id` and
--   `strava_activities.projected_daily_log_id` for traceability.
CREATE OR REPLACE FUNCTION project_strava_activity_to_apex(
  p_strava_activity_id bigint,
  p_day_type text DEFAULT 'moderate',
  p_user_id text DEFAULT 'sergio'
)
RETURNS uuid AS $$
DECLARE
  v_strava           strava_activities;
  v_daily_log        daily_log;
  v_activity_id      uuid;
  v_sport            text;
  v_distance_km      numeric(8,2);
  v_moving_time      text;
  v_extra_stats      jsonb;
  v_zones            jsonb;
BEGIN
  SELECT * INTO v_strava
  FROM strava_activities
  WHERE strava_activity_id = p_strava_activity_id
    AND user_id = p_user_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'strava_activities row not found for activity_id=% and user_id=%',
      p_strava_activity_id, p_user_id;
  END IF;

  SELECT * INTO v_daily_log
  FROM get_or_create_daily_log(v_strava.started_at::date, p_day_type, p_user_id);

  v_sport := map_strava_sport_to_apex_sport(v_strava.sport_type);
  v_distance_km := ROUND((coalesce(v_strava.distance_meters, 0) / 1000.0)::numeric, 2);
  v_moving_time := to_char((coalesce(v_strava.moving_time_seconds, 0) || ' seconds')::interval, 'HH24:MI:SS');

  SELECT jsonb_agg(
           jsonb_build_object(
             'label', item.label,
             'value', item.value
           )
         )
  INTO v_extra_stats
  FROM (
    VALUES
      ('sport_type', v_strava.sport_type),
      ('suffer_score', coalesce(v_strava.suffer_score::text, '')),
      ('kilojoules', coalesce(v_strava.kilojoules::text, '')),
      ('avg_watts', coalesce(v_strava.average_watts::text, '')),
      ('avg_speed_mps', coalesce(v_strava.average_speed_mps::text, '')),
      ('moving_time_seconds', coalesce(v_strava.moving_time_seconds::text, '')),
      ('elevation_m', coalesce(v_strava.total_elevation_gain_meters::text, ''))
  ) AS item(label, value)
  WHERE item.value <> '';

  SELECT jsonb_agg(
           jsonb_build_object(
             'zone', zone_index,
             'resource', resource,
             'seconds', time_seconds,
             'pct',
               CASE
                 WHEN coalesce(v_strava.moving_time_seconds, 0) = 0 THEN 0
                 ELSE ROUND((time_seconds::numeric / v_strava.moving_time_seconds::numeric) * 100, 2)
               END,
             'min', min_value,
             'max', max_value
           )
           ORDER BY resource, zone_index
         )
  INTO v_zones
  FROM strava_activity_zones z
  WHERE z.strava_activity_id = v_strava.id;

  INSERT INTO activities (
    daily_log_id,
    user_id,
    title,
    sport,
    calories,
    distance,
    distance_unit,
    elevation,
    moving_time,
    avg_hr,
    extra_stats,
    zones,
    achievements,
    gpx_url,
    source,
    external_id,
    started_at,
    updated_at,
    raw_source
  )
  VALUES (
    v_daily_log.id,
    p_user_id,
    v_strava.name,
    v_sport,
    COALESCE(ROUND(v_strava.kilojoules), 0),
    v_distance_km,
    'km',
    COALESCE(ROUND(v_strava.total_elevation_gain_meters), 0),
    v_moving_time,
    CASE
      WHEN v_strava.average_heartrate IS NULL THEN NULL
      ELSE ROUND(v_strava.average_heartrate)::integer
    END,
    COALESCE(v_extra_stats, '[]'::jsonb),
    COALESCE(v_zones, '[]'::jsonb),
    '[]'::jsonb,
    NULL,
    'strava',
    v_strava.strava_activity_id::text,
    v_strava.started_at,
    now(),
    v_strava.raw_payload
  )
  ON CONFLICT (source, external_id) DO UPDATE SET
    daily_log_id = excluded.daily_log_id,
    user_id = excluded.user_id,
    title = excluded.title,
    sport = excluded.sport,
    calories = excluded.calories,
    distance = excluded.distance,
    distance_unit = excluded.distance_unit,
    elevation = excluded.elevation,
    moving_time = excluded.moving_time,
    avg_hr = excluded.avg_hr,
    extra_stats = excluded.extra_stats,
    zones = excluded.zones,
    achievements = excluded.achievements,
    gpx_url = excluded.gpx_url,
    started_at = excluded.started_at,
    updated_at = excluded.updated_at,
    raw_source = excluded.raw_source
  RETURNING id INTO v_activity_id;

  UPDATE strava_activities
  SET projected_activity_id = v_activity_id,
      projected_daily_log_id = v_daily_log.id,
      updated_at = now()
  WHERE id = v_strava.id;

  RETURN v_activity_id;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- 11. OPTIONAL VIEW: STRAVA ACTIVITY SUMMARY FOR AGENTS / UI
-- ============================================================
CREATE OR REPLACE VIEW strava_activity_projection_status AS
SELECT
  sa.id,
  sa.user_id,
  sa.strava_activity_id,
  sa.name,
  sa.sport_type,
  sa.started_at,
  sa.deleted,
  sa.projected_activity_id,
  sa.projected_daily_log_id,
  a.title AS projected_title,
  a.sport AS projected_sport,
  dl.log_date AS projected_log_date,
  sa.updated_at
FROM strava_activities sa
LEFT JOIN activities a ON a.id = sa.projected_activity_id
LEFT JOIN daily_log dl ON dl.id = sa.projected_daily_log_id;
