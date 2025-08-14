-- :name bars.window :many
SELECT ticker, date, open, high, low, close, volume
FROM bars
WHERE ticker = :ticker
  AND date >= :start
  AND date <= :end
ORDER BY date;

-- :name bars.upsert :affected
INSERT INTO bars (ticker, date, open, high, low, close, volume)
VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
ON CONFLICT(ticker, date) DO UPDATE SET
  open = excluded.open,
  high = excluded.high,
  low  = excluded.low,
  close= excluded.close,
  volume = excluded.volume;
