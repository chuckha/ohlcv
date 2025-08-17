-- Migration: symbol_meta_stop_after
-- Version: 0003
-- Created: 2025-08-15T19:43:03Z

-- Write forward-only SQL below
ALTER TABLE symbol_meta ADD COLUMN stop_after TEXT;
CREATE INDEX IF NOT EXISTS idx_symbol_meta_stop_after ON symbol_meta(stop_after);
