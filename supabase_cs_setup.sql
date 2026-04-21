-- Duflat CS (Customer Support) — Review Monitoring Tables
-- Completely separate from social_* tables.
-- Run in Supabase SQL Editor (Dashboard → SQL Editor → New query → Run)

-- Table 1: Individual reviews from Apple App Store and Google Play
CREATE TABLE IF NOT EXISTS cs_reviews (
    id BIGSERIAL PRIMARY KEY,
    review_hash TEXT UNIQUE NOT NULL,          -- dedupe key: platform|country|platform_review_id
    platform TEXT NOT NULL CHECK (platform IN ('apple', 'google_play')),
    app_id TEXT NOT NULL,                       -- 'tv.danmaku.bili' (gplay) or '736303417' (apple)
    platform_review_id TEXT DEFAULT '',         -- native id from the store, if exposed
    country TEXT NOT NULL,                      -- ISO 3166-1 alpha-2 lowercase ('us', 'jp', ...)
    language TEXT DEFAULT '',                   -- detected or locale hint
    author TEXT DEFAULT '',
    rating INT CHECK (rating BETWEEN 1 AND 5),
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    app_version TEXT DEFAULT '',
    review_date TIMESTAMPTZ,                    -- when the review was written
    fetched_at TIMESTAMPTZ DEFAULT NOW(),       -- when we pulled it
    raw JSONB DEFAULT '{}'::jsonb
);

-- Table 2: Poll log — one row per platform+country batch
CREATE TABLE IF NOT EXISTS cs_poll_log (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    platform TEXT NOT NULL,
    country TEXT NOT NULL,
    reviews_fetched INT DEFAULT 0,
    reviews_new INT DEFAULT 0,
    error TEXT DEFAULT ''
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_cs_reviews_date ON cs_reviews(review_date DESC);
CREATE INDEX IF NOT EXISTS idx_cs_reviews_platform ON cs_reviews(platform);
CREATE INDEX IF NOT EXISTS idx_cs_reviews_country ON cs_reviews(country);
CREATE INDEX IF NOT EXISTS idx_cs_reviews_rating ON cs_reviews(rating);
CREATE INDEX IF NOT EXISTS idx_cs_reviews_fetched ON cs_reviews(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_cs_poll_log_time ON cs_poll_log(started_at DESC);

-- Disable RLS for API access (anon key)
ALTER TABLE cs_reviews DISABLE ROW LEVEL SECURITY;
ALTER TABLE cs_poll_log DISABLE ROW LEVEL SECURITY;

-- Grant access to anon role
GRANT ALL ON cs_reviews TO anon;
GRANT ALL ON cs_poll_log TO anon;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon;
