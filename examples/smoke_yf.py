from ohlcv import configure, get_ohlcv_df
import logging
logging.basicConfig(level=logging.INFO)                # set root handler >= INFO
logging.getLogger("ohlcv").setLevel(logging.INFO)     # or target the package

# pick a DB path per-project (isolated data)
configure(dsn="sqlite:///./data/database.sqlite3", availability="clip")

mi = get_ohlcv_df(["THRD","MSFT","CRWV","CURA.TO","IPX.AX"], "2025-01-02", "2025-08-15")
print(mi.columns)        # MultiIndex: (field, ticker)
print(mi.tail())
