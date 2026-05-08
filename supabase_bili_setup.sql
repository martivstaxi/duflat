-- Duflat Bilibili cross-post monitor — persistent storage.
-- Replaces ephemeral data/bili_status.json on Railway (wiped on every redeploy).
-- Run in Supabase SQL Editor (Dashboard → SQL Editor → New query → Run).

-- One row per creator. payload holds the full check_creator() result;
-- manager column is duplicated for index/filter performance.
CREATE TABLE IF NOT EXISTS bili_creator_status (
    bilibili_mid TEXT PRIMARY KEY,
    manager      TEXT,
    name         TEXT,
    payload      JSONB NOT NULL,
    checked_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bili_status_manager ON bili_creator_status(manager);
CREATE INDEX IF NOT EXISTS idx_bili_status_checked ON bili_creator_status(checked_at DESC);

-- One row per refresh run (cron or manual). last_global_run = MAX(finished_at).
CREATE TABLE IF NOT EXISTS bili_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    creators_total  INT DEFAULT 0,
    creators_done   INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bili_runs_finished ON bili_runs(finished_at DESC NULLS LAST);

-- Mirror the existing modules: anon access, no RLS.
ALTER TABLE bili_creator_status DISABLE ROW LEVEL SECURITY;
ALTER TABLE bili_runs            DISABLE ROW LEVEL SECURITY;

GRANT ALL ON bili_creator_status TO anon;
GRANT ALL ON bili_runs            TO anon;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon;
