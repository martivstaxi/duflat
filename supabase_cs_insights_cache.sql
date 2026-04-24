-- Cache for /cs/insights Haiku narrative.
-- One row per (period, lang); TTL enforced in Python (12h) against
-- generated_at. Poll completion (total_new > 0) clears the table so the
-- next click regenerates against fresh data.
-- Run once in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS cs_insights_cache (
    id           SERIAL PRIMARY KEY,
    period       TEXT NOT NULL,            -- '7d' | '30d' | 'year'
    lang         TEXT NOT NULL,            -- 'en' | 'zh'
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload      JSONB NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS cs_insights_cache_period_lang_idx
    ON cs_insights_cache (period, lang);
