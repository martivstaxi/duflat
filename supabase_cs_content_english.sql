-- Add content_english column to cs_reviews.
-- Populated by Haiku on save (and via POST /cs/backfill-translations for pre-existing rows).
ALTER TABLE cs_reviews
    ADD COLUMN IF NOT EXISTS content_english TEXT DEFAULT '';
