-- Migration: init
-- Version: 0001
-- Created: 2025-08-14Z

CREATE TABLE IF NOT EXISTS bars (
  ticker TEXT NOT NULL,
  date   TEXT NOT NULL, -- YYYY-MM-DD
  open   REAL NOT NULL,
  high   REAL NOT NULL,
  low    REAL NOT NULL,
  close  REAL NOT NULL,
  volume INTEGER NOT NULL,
  PRIMARY KEY (ticker, date)
);

-- for common window scans
CREATE INDEX IF NOT EXISTS idx_bars_ticker_date ON bars(ticker, date);

