-- :name symbol_meta.get_one :one
SELECT ticker, first_seen_date, last_seen_date, skip_before
FROM symbol_meta
WHERE ticker = :ticker;

-- :name symbol_meta.upsert_bounds :affected
INSERT INTO symbol_meta (ticker, first_seen_date, last_seen_date, updated_at)
VALUES (:ticker, :first_seen_date, :last_seen_date, :updated_at)
ON CONFLICT(ticker) DO UPDATE SET
  first_seen_date = CASE
    WHEN excluded.first_seen_date IS NULL THEN symbol_meta.first_seen_date
    WHEN symbol_meta.first_seen_date IS NULL THEN excluded.first_seen_date
    WHEN excluded.first_seen_date < symbol_meta.first_seen_date THEN excluded.first_seen_date
    ELSE symbol_meta.first_seen_date
  END,
  last_seen_date = CASE
    WHEN excluded.last_seen_date IS NULL THEN symbol_meta.last_seen_date
    WHEN symbol_meta.last_seen_date IS NULL THEN excluded.last_seen_date
    WHEN excluded.last_seen_date > symbol_meta.last_seen_date THEN excluded.last_seen_date
    ELSE symbol_meta.last_seen_date
  END,
  updated_at = excluded.updated_at;

-- :name symbol_meta.advance_skip_before :affected
INSERT INTO symbol_meta (ticker, skip_before, updated_at)
VALUES (:ticker, :skip_before, :updated_at)
ON CONFLICT(ticker) DO UPDATE SET
  skip_before = CASE
    WHEN symbol_meta.skip_before IS NULL THEN excluded.skip_before
    WHEN excluded.skip_before > symbol_meta.skip_before THEN excluded.skip_before
    ELSE symbol_meta.skip_before
  END,
  updated_at = excluded.updated_at;

-- :name symbol_meta.advance_stop_after :affected
INSERT INTO symbol_meta (ticker, stop_after, updated_at)
VALUES (:ticker, :stop_after, :updated_at)
ON CONFLICT(ticker) DO UPDATE SET
  stop_after = CASE
    WHEN symbol_meta.stop_after IS NULL THEN excluded.stop_after
    WHEN excluded.stop_after > symbol_meta.stop_after THEN excluded.stop_after
    ELSE symbol_meta.stop_after
  END,
  updated_at = excluded.updated_at;
