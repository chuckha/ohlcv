from __future__ import annotations
from typing import Sequence
from datetime import date
import pandas as pd

from lightql import connect, load_queries
from .protocols import Store

REQUIRED_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]


class SqlStore(Store):
    """SQLite-backed Store using lightql queries.

    - Expects a `bars` table with PRIMARY KEY (ticker, date).
    - Uses simple per-ticker window reads to avoid complex IN parameter binding.
    """

    def __init__(self, dsn: str | None = None, sql_dir: str = "sql") -> None:
        self.conn = connect(dsn)
        self.q = load_queries(sql_dir, self.conn)

    def read_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for t in tickers:
            rows = self.q.bars.window(ticker=t, start=_to_datestr(start), end=_to_datestr(end))
            if rows:
                df = pd.DataFrame(rows)
                frames.append(df)
        if not frames:
            return _empty_df()
        out = pd.concat(frames, ignore_index=True)
        # normalize types
        out = out.reindex(columns=REQUIRED_COLS)
        out["ticker"] = out["ticker"].astype(str).str.upper()
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        for c in ["open", "high", "low", "close"]:
            out[c] = out[c].astype(float)
        out["volume"] = out["volume"].astype("int64", errors="ignore")
        return out

    def upsert_df(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return

        df = df.reindex(columns=REQUIRED_COLS).copy()
        df["ticker"] = df["ticker"].astype(str).str.upper()
        df["date"] = pd.to_datetime(df["date"]).dt.date.apply(_to_datestr)
        for c in ["open","high","low","close"]:
            df[c] = df[c].astype(float)
        df["volume"] = df["volume"].astype("int64", errors="ignore")

        records = df.to_dict("records")
        CHUNK = 1000
        for i in range(0, len(records), CHUNK):
            chunk = records[i:i+CHUNK]
            self.conn.conn.execute("BEGIN")  # start txn on the underlying sqlite3.Connection
            try:
                for rec in chunk:
                    self.q.bars.upsert(**rec)
                self.conn.commit()
            except Exception:
                # best‑effort rollback
                try: self.conn.conn.execute("ROLLBACK")
                except Exception: pass
                raise

def _to_datestr(d: date) -> str:
    return d.isoformat()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)
