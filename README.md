# OHLCV Skeleton (Protocol-based, Minimal)

One public function, local-first with fetch-on-miss, returning a tidy daily OHLCV DataFrame.

## Install (editable)
```bash
poetry add --path . --editable
```

## Public API
```python
from ohlcv import get_ohlcv_df
from ohlcv.protocols import Store, Provider

df = get_ohlcv_df(["KOS", "ATEC"], "2025-01-01", "2025-06-30", store=my_store, provider=my_provider)
```

- Returns a DataFrame with columns: `ticker, date, open, high, low, close, volume` (long/tidy).
- Guarantees contiguity by *sessions* (see calendar below) or raises `DataNotContiguous`.

## Implement the seams
Provide minimal concrete classes that satisfy the Protocols.

```python
# store.py (example sketch)
import pandas as pd
from typing import Sequence
from datetime import date

class SqlStore:
    def __init__(self, conn):
        self.conn = conn  # e.g., lightql ConnectionWrapper or DB-API
    def read_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        ...  # SELECT * FROM bars WHERE ticker IN (...) AND date BETWEEN ...
    def upsert_df(self, df: pd.DataFrame) -> None:
        ...  # UPSERT by (ticker,date)

# provider.py (example sketch)
class MyProvider:
    def fetch_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        ...  # call upstream and return tidy DF in the expected schema
```

## Calendar
Default `ohlcv.calendar.sessions` is weekday-only (Mon–Fri). Replace with an exchange-aware implementation for production.

## Behavior
- Normalize tickers to UPPERCASE.
- Parse `YYYY-MM-DD` strings to dates.
- Compute gaps via expected sessions; fetch only missing spans; upsert; re-read; validate.
- Set `include_partial=True` to return even if gaps remain.

## Tests (suggested)
- Given an empty store, provider returns rows for the window → final DF contiguous.
- With partial store coverage, provider called **only** for missing spans.
- When provider can’t fill, `DataNotContiguous` raised with correct spans.

## Wire `SqlStore` with `lightql`

```python
from ohlcv import get_ohlcv_df
from ohlcv.sql_store import SqlStore

# 1) Run migrations once (CLI from lightql):
# lightql migrations apply --sql-dir sql --dsn sqlite:///app.db

# 2) Use the store in your app
store = SqlStore(dsn="sqlite:///app.db", sql_dir="sql")
provider = ...  # your Provider implementation

df = get_ohlcv_df(["KOS", "ATEC"], "2025-01-01", "2025-03-31", store=store, provider=provider)
print(df.head())
```

## Notes
- `bars.window` reads per ticker to keep list-parameter handling simple.
- Upserts are per-row for clarity. If you need speed, add a bulk insert query (e.g., `:script`) and batch values.
- Dates are stored as `YYYY-MM-DD` TEXT in SQLite; the service normalizes to pandas datetime on read.
