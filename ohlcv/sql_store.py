from __future__ import annotations
from typing import Sequence, Dict, Tuple, Optional
from datetime import date, datetime, timedelta
import pandas as pd

from lightql import connect, load_queries
from .protocols import Store
from .utils import TIDY_COLS
from .resources import unpack_sql_package


class SqlStore(Store):
    """SQLite-backed Store using lightql; SQL loaded from packaged resources.

    Adds symbol_meta helpers for IPO-aware pruning.
    """
    def __init__(self, dsn: str | None = None):
        self.conn = connect(dsn)
        self._sql_dir = unpack_sql_package()
        self.q = load_queries(str(self._sql_dir), self.conn)

    def read_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for t in [str(x).upper() for x in tickers]:
            rows = self.q.execute("bars.window", ticker=t, start=_ds(start), end=_ds(end))
            if rows:
                frames.append(pd.DataFrame(rows))
        if not frames:
            return _empty_tidy()
        out = pd.concat(frames, ignore_index=True)
        out = out.reindex(columns=TIDY_COLS)
        out["ticker"] = out["ticker"].astype(str).str.upper()
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        for c in ["open","high","low","close"]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype("int64")
        out = out.dropna(subset=["open","high","low","close"]).copy()
        return out

    def upsert_df(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        df = df.reindex(columns=TIDY_COLS).copy()
        df["ticker"] = df["ticker"].astype(str).str.upper()
        df["date"] = pd.to_datetime(df["date"]).dt.date.apply(_ds)
        for c in ["open","high","low","close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
        recs = df.to_dict("records")
        # transactional chunk
        CHUNK = 1000
        for i in range(0, len(recs), CHUNK):
            chunk = recs[i:i+CHUNK]
            self.conn.conn.execute("BEGIN")
            try:
                for r in chunk:
                    self.q.execute("bars.upsert", **r)
                self.conn.commit()
            except Exception:
                try: self.conn.conn.execute("ROLLBACK")
                except Exception: pass
                raise

    def get_meta(self, tickers: Sequence[str]) -> Dict[str, Dict[str, Optional[str]]]:
        out: Dict[str, Dict[str, Optional[str]]] = {}
        print([k for k in self.q._queries.keys() if k.startswith("symbol_meta")])
        for t in [str(x).upper() for x in tickers]:
            try:
                row = self.q.execute("symbol_meta.get_one", ticker=t)
            except Exception:
                row = None
            if not row:
                out[t] = {"first_seen_date": None, "last_seen_date": None, "skip_before": None}
            else:
                out[t] = {
                    "first_seen_date": row.get("first_seen_date"),
                    "last_seen_date": row.get("last_seen_date"),
                    "skip_before": row.get("skip_before"),
                }
        return out

    def upsert_bounds_from_df(self, tidy: pd.DataFrame) -> None:
        if tidy is None or tidy.empty:
            return
        grp = tidy.groupby("ticker")["date"].agg(["min", "max"]).reset_index()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        for _, r in grp.iterrows():
            t = str(r["ticker"]).upper()
            dmin = pd.to_datetime(r["min"]).date().isoformat()
            dmax = pd.to_datetime(r["max"]).date().isoformat()
            self.q.execute(
                "symbol_meta.upsert_bounds",
                ticker=t,
                first_seen_date=dmin,
                last_seen_date=dmax,
                updated_at=now,
            )

    def advance_skip_before(self, ticker: str, when_date: date) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self.q.execute(
            "symbol_meta.advance_skip_before",
            ticker=str(ticker).upper(),
            skip_before=when_date.isoformat(),
            updated_at=now,
        )


def _ds(d: date) -> str:
    return d.isoformat()


def _empty_tidy() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=TIDY_COLS)
