from ohlcv import get_ohlcv_df, YFProvider
from ohlcv.sql_store import SqlStore
from ohlcv.errors import DataNotContiguous
import logging
logging.basicConfig(level=logging.DEBUG)  # or DEBUG

if __name__ == "__main__":
    store = SqlStore(dsn="sqlite:///./data/database.sqlite3", sql_dir="sql")
    provider = YFProvider(auto_adjust=False)

    # Try to get data with strict contiguity first, fall back to partial if market holidays interfere
    df = get_ohlcv_df(["ETSY", "GME"], "2025-01-02", "2025-01-16", store=store, provider=provider, include_partial=True)

    print(df.tail())

    # run again to confirm cache/local-first behavior (should fetch zero and just read)
    df2 = get_ohlcv_df(["ETSY", "GME"], "2025-01-02", "2025-01-16", store=store, provider=provider, include_partial=True)
    print("rows:", len(df2))
