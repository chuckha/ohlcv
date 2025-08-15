from ohlcv import get_ohlcv_df, YFProvider
from ohlcv.sql_store import SqlStore

if __name__ == "__main__":
    store = SqlStore(dsn="sqlite:///./data/database.sqlite3", sql_dir="sql")
    provider = YFProvider(auto_adjust=False)
    df = get_ohlcv_df(["AAPL", "MSFT"], "2025-01-02", "2025-01-16", store=store, provider=provider)
    print(df.tail())

    # run again to confirm cache/local-first behavior (should fetch zero and just read)
    df2 = get_ohlcv_df(["AAPL", "MSFT"], "2025-01-02", "2025-01-16", store=store, provider=provider)
    print("rows:", len(df2))
