from ohlcv import get_ohlcv_df, configure
import logging
logging.basicConfig(level=logging.INFO)  # or DEBUG

if __name__ == "__main__":
    # Configure once (or set env LIGHTQL_DATABASE_URL / OHLCV_SQL_DIR / OHLCV_MARKET)
    configure(dsn="sqlite:///./data/database.sqlite3", sql_dir="sql", market="XNYS")

    df = get_ohlcv_df(["CRWV", "MSFT"], "2025-01-12", "2025-04-20")
    import pdb; pdb.set_trace()
    print(df.tail())
