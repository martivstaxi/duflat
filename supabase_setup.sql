-- Duflat Social Listening — Supabase Table Setup
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New query → Run)

-- Table 1: Tracked source URLs
CREATE TABLE IF NOT EXISTS social_sources (
    id BIGSERIAL PRIMARY KEY,
    url_hash TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    domain TEXT DEFAULT '',
    has_2026_content BOOLEAN DEFAULT FALSE,
    checked_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table 2: Analyzed mentions (individual reviews/comments)
CREATE TABLE IF NOT EXISTS social_mentions (
    id BIGSERIAL PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,
    url TEXT DEFAULT '',
    url_hash TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    author TEXT DEFAULT '',
    country TEXT DEFAULT '',
    language TEXT DEFAULT '',
    sentiment TEXT DEFAULT 'neutral' CHECK (sentiment IN ('positive', 'negative', 'neutral')),
    sensitivity TEXT DEFAULT 'low' CHECK (sensitivity IN ('low', 'medium', 'high', 'critical')),
    source_type TEXT DEFAULT 'news_minor' CHECK (source_type IN ('government', 'news_major', 'news_minor', 'blog', 'forum', 'social', 'financial')),
    content_original TEXT DEFAULT '',
    content_english TEXT DEFAULT '',
    keywords TEXT[] DEFAULT '{}',
    content_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table 3: Scan log (daily stats)
CREATE TABLE IF NOT EXISTS social_scan_log (
    id BIGSERIAL PRIMARY KEY,
    scan_date DATE DEFAULT CURRENT_DATE,
    links_received INT DEFAULT 0,
    links_new INT DEFAULT 0,
    links_with_2026 INT DEFAULT 0,
    mentions_saved INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_mentions_date ON social_mentions(content_date DESC);
CREATE INDEX IF NOT EXISTS idx_mentions_sentiment ON social_mentions(sentiment);
CREATE INDEX IF NOT EXISTS idx_mentions_sensitivity ON social_mentions(sensitivity);
CREATE INDEX IF NOT EXISTS idx_mentions_source_type ON social_mentions(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_hash ON social_sources(url_hash);

-- Disable RLS for API access (anon key)
ALTER TABLE social_sources DISABLE ROW LEVEL SECURITY;
ALTER TABLE social_mentions DISABLE ROW LEVEL SECURITY;
ALTER TABLE social_scan_log DISABLE ROW LEVEL SECURITY;

-- Grant access to anon role
GRANT ALL ON social_sources TO anon;
GRANT ALL ON social_mentions TO anon;
GRANT ALL ON social_scan_log TO anon;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon;
