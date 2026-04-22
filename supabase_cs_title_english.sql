-- Add title_english column to cs_reviews (Apple reviews have titles;
-- Google Play does not). Populated by Haiku alongside content_english.
ALTER TABLE cs_reviews
    ADD COLUMN IF NOT EXISTS title_english TEXT DEFAULT '';
