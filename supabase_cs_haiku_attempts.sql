-- Track how many times backfill_translations has tried to enrich a row.
-- After MAX_HAIKU_ATTEMPTS (see modules/cs_reviews/haiku.py), the row is
-- skipped to avoid infinite retry loops on Haiku-refractory content
-- (emoji-only, one-word reviews, etc.).
-- Run once in Supabase SQL Editor.

ALTER TABLE cs_reviews
    ADD COLUMN IF NOT EXISTS haiku_attempts INT DEFAULT 0;
