-- Migration: symbol_meta
-- Version: 0002
-- Created: 2025-08-15T18:57:16Z
CREATE TABLE IF NOT EXISTS symbol_meta (
  ticker TEXT PRIMARY KEY,
  first_seen_date TEXT,  -- YYYY-MM-DD (earliest date we've actually stored)
  last_seen_date  TEXT,  -- YYYY-MM-DD (latest date we've actually stored)
  skip_before     TEXT,  -- YYYY-MM-DD (do not refetch strictly before or on this date)
  updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbol_meta_first ON symbol_meta(first_seen_date);
CREATE INDEX IF NOT EXISTS idx_symbol_meta_last  ON symbol_meta(last_seen_date);
