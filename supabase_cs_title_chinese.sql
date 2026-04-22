-- Add title_chinese column to cs_reviews (Simplified Chinese translation of
-- title_english; Apple reviews carry titles, Google Play does not).
-- Populated by Haiku alongside title_english.
ALTER TABLE cs_reviews
    ADD COLUMN IF NOT EXISTS title_chinese TEXT DEFAULT '';
