-- Add content_chinese column to cs_reviews (Simplified Chinese translation of
-- content_english). Populated by Haiku on save, and via POST /cs/backfill-translations
-- for pre-existing rows. Mirrors the social_mentions.content_chinese pattern.
ALTER TABLE cs_reviews
    ADD COLUMN IF NOT EXISTS content_chinese TEXT DEFAULT '';
