-- Duflat CS — Country state + poll log extension
-- Safe to re-run; all operations are IF NOT EXISTS.

-- Table: per (platform, country) scan status
CREATE TABLE IF NOT EXISTS cs_country_state (
    id BIGSERIAL PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('apple', 'google_play')),
    country TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('active', 'inactive', 'unknown')),
    last_poll_at TIMESTAMPTZ,
    last_active_at TIMESTAMPTZ,
    last_review_count INT DEFAULT 0,
    consecutive_empty_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_cs_country UNIQUE (platform, country)
);

CREATE INDEX IF NOT EXISTS idx_cs_country_state_status ON cs_country_state(status);
CREATE INDEX IF NOT EXISTS idx_cs_country_state_last_poll ON cs_country_state(last_poll_at DESC);

ALTER TABLE cs_country_state DISABLE ROW LEVEL SECURITY;
GRANT ALL ON cs_country_state TO anon;

-- Extend cs_poll_log with the full_scan marker so the next discovery
-- cycle can be scheduled from the last flagged row.
ALTER TABLE cs_poll_log ADD COLUMN IF NOT EXISTS full_scan BOOLEAN DEFAULT FALSE;
ALTER TABLE cs_poll_log ADD COLUMN IF NOT EXISTS countries_scanned INT DEFAULT 0;
ALTER TABLE cs_poll_log ADD COLUMN IF NOT EXISTS countries_skipped INT DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_cs_poll_log_full_scan ON cs_poll_log(started_at DESC) WHERE full_scan = TRUE;
