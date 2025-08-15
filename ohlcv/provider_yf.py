from __future__ import annotations
from datetime import date, timedelta
from typing import Sequence
import pandas as pd
import yfinance as yf

from .protocols import Provider

REQUIRED_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]

class YFProvider(Provider):
    """yfinance Provider for daily OHLCV using yf.download (robust), with tidy normalization."""

    def __init__(self, *, auto_adjust: bool = False):
        if auto_adjust:
            raise ValueError("Store policy: only raw (unadjusted) OHLCV allowed; set auto_adjust=False")
        self.auto_adjust = False

    def fetch_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        tks = [str(t).upper().strip() for t in tickers]
        if not tks:
            return _empty_df()

        # yfinance end is exclusive; widen to avoid boundary holes
        yf_start = start - timedelta(days=2)
        yf_end   = end + timedelta(days=2)

        frames: list[pd.DataFrame] = []

        # 1) Bulk path via yf.download (handles multi-ticker reliably)
        bulk = _download_bulk(tks, yf_start, yf_end, auto_adjust=self.auto_adjust)
        if bulk is not None and not bulk.empty:
            frames.append(_normalize_trim(bulk, start, end))

        # 2) Per-ticker fallback for any symbols missing from bulk
        got = set(frames[0]["ticker"].unique()) if frames else set()
        for t in tks:
            if t in got:
                continue
            one = _download_one(t, yf_start, yf_end, auto_adjust=self.auto_adjust)
            if one is None or one.empty:
                continue
            frames.append(_normalize_trim(one, start, end))

        if not frames:
            return _empty_df()
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["ticker", "date"]).copy()
        return out.sort_values(["ticker", "date"]).reset_index(drop=True).reindex(columns=REQUIRED_COLS)

# ---- helpers ----

def _download_bulk(tickers: Sequence[str], start: date, end: date, *, auto_adjust: bool) -> pd.DataFrame | None:
    try:
        df = yf.download(
            tickers=list(tickers),
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=auto_adjust,
            repair=True,
            progress=False,
            group_by="ticker",  # MultiIndex: (ticker, field)
            threads=False,
        )
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    return _flatten_download(df)

def _download_one(ticker: str, start: date, end: date, *, auto_adjust: bool) -> pd.DataFrame | None:
    try:
        df = yf.download(
            tickers=ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=auto_adjust,
            repair=True,
            progress=False,
            group_by="column",  # flat columns
            threads=False,
        )
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None

    # Handle MultiIndex columns that can occur even with group_by="column" for single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if col[1] == '' else col[1] for col in df.columns]

    df = df.copy().reset_index()
    if "Date" in df.columns: df.rename(columns={"Date": "date"}, inplace=True)
    if "Datetime" in df.columns: df.rename(columns={"Datetime": "date"}, inplace=True)
    df.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Volume": "volume",
    }, inplace=True)
    if "Adj Close" in df.columns:
        df["adj_close"] = df["Adj Close"]
    df["ticker"] = ticker
    keep = [c for c in ["ticker","date","open","high","low","close","volume"] if c in df.columns]
    return df[keep]

def _flatten_download(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yf.download multi-ticker frame into tidy rows."""
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    frames: list[pd.DataFrame] = []
    if isinstance(df.columns, pd.MultiIndex) and df.columns.nlevels >= 2:
        for t in df.columns.get_level_values(0).unique():
            sub = df[t].copy().reset_index()
            if "Date" in sub.columns: sub.rename(columns={"Date": "date"}, inplace=True)
            if "Datetime" in sub.columns: sub.rename(columns={"Datetime": "date"}, inplace=True)
            sub.rename(columns={
                "Open":"open","High":"high","Low":"low","Close":"close",
                "Volume":"volume",
            }, inplace=True)
            if "Adj Close" in sub.columns:
                sub["adj_close"] = sub["Adj Close"]
            sub["ticker"] = str(t).upper()
            keep = [c for c in ["ticker","date","open","high","low","close","volume"] if c in sub.columns]
            frames.append(sub[keep])
    else:
        sub = df.copy().reset_index()
        if "Date" in sub.columns: sub.rename(columns={"Date":"date"}, inplace=True)
        if "Datetime" in sub.columns: sub.rename(columns={"Datetime":"date"}, inplace=True)
        sub.rename(columns={
            "Open":"open","High":"high","Low":"low","Close":"close",
            "Volume":"volume",
        }, inplace=True)
        if "Adj Close" in sub.columns:
            sub["adj_close"] = sub["Adj Close"]
        frames.append(sub)

    if not frames:
        return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.concat(frames, ignore_index=True)

def _normalize_trim(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    d = df.copy()

    # Ensure required numeric cols exist (fill missing gracefully)
    for c in ["open","high","low","close"]:
        if c not in d.columns:
            d[c] = pd.NA
    if "volume" not in d.columns:
        d["volume"] = 0

    if "date" not in d.columns:
        return pd.DataFrame(columns=REQUIRED_COLS)

    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).copy()
    try:
        d["date"] = d["date"].dt.tz_localize(None)
    except TypeError:
        pass
    d["date"] = d["date"].dt.normalize()

    for c in ["open","high","low","close"]:
        if c in d.columns:
            if isinstance(d[c], pd.DataFrame):
                d[c] = d[c].iloc[:, 0]
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0).astype("int64")

    d = d.dropna(subset=["open","high","low","close"]).copy()

    if "ticker" not in d.columns:
        # single-ticker bulk fallback; caller usually assigns, but keep safe
        d["ticker"] = "UNKNOWN"

    mask = (d["date"] >= pd.to_datetime(start)) & (d["date"] <= pd.to_datetime(end))
    d = d.loc[mask, ["ticker","date","open","high","low","close","volume"]]
    return d

def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)
