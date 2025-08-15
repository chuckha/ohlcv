from ohlcv import configure, get_ohlcv_df
import logging
logging.basicConfig(level=logging.INFO)                # set root handler >= INFO
logging.getLogger("ohlcv").setLevel(logging.INFO)     # or target the package

# pick a DB path per-project (isolated data)
configure(dsn="sqlite:///./data/database.sqlite3", market="NYSE", availability="clip")

mi = get_ohlcv_df(["AAPL","MSFT","CRWV"], "2025-01-02", "2025-04-20")
print(mi.columns)        # MultiIndex: (field, ticker)
print(mi.tail())
