from __future__ import annotations
from datetime import date, timedelta
from typing import Sequence
import pandas as pd
import yfinance as yf

from .protocols import Provider

REQUIRED_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]


class YFProvider(Provider):
    """yfinance-backed Provider for daily OHLCV.

    - Fetches per (ticker, span) to match the service's gap-filling flow.
    - Returns tidy DataFrame with REQUIRED_COLS.
    - Stores **raw** (unadjusted) OHLCV; ignore `Adj Close`.
    """

    def __init__(self, *, auto_adjust: bool = False):
        self.auto_adjust = bool(auto_adjust)

    def fetch_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        if not tickers:
            return _empty_df()
        # yfinance's `end` is exclusive; include the last day by +1
        yf_end = end + timedelta(days=1)
        for t in tickers:
            t_sym = str(t).upper().strip()
            try:
                hist = yf.Ticker(t_sym).history(
                    start=start.isoformat(),
                    end=yf_end.isoformat(),
                    interval="1d",
                    auto_adjust=self.auto_adjust,
                    actions=False,
                )
            except Exception:
                # Network or symbol-specific failure → treat as empty for this span
                continue
            if hist is None or hist.empty:
                continue

            # Keep only the columns we need
            cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in hist.columns]
            if not cols:
                continue
            df = hist[cols].copy()
            df.reset_index(inplace=True)  # brings Date/Datetime into a column
            # Robust rename for different index labels
            rename_map = {
                "Date": "date",
                "Datetime": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            df.rename(columns=rename_map, inplace=True)
            if "date" not in df.columns:
                # Fallback if index name was something else after reset
                if "index" in df.columns:
                    df.rename(columns={"index": "date"}, inplace=True)
                else:
                    # last resort: construct from RangeIndex (skip)
                    continue

            # Normalize types
            df["ticker"] = t_sym
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            # Drop invalid dates
            df = df.dropna(subset=["date"]).copy()
            # Strip tz if present, then normalize to midnight
            try:
                df["date"] = df["date"].dt.tz_localize(None)
            except TypeError:
                # already tz-naive
                pass
            df["date"] = df["date"].dt.normalize()

            for c in ["open", "high", "low", "close"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if "volume" in df.columns:
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

            # Drop rows missing core OHLC
            df = df.dropna(subset=["open", "high", "low", "close"]).copy()

            # Keep within [start, end] inclusive (history end was exclusive already)
            mask = (df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))
            df = df.loc[mask, ["ticker", "date", "open", "high", "low", "close", "volume"]]
            if not df.empty:
                frames.append(df)

        if not frames:
            return _empty_df()
        out = pd.concat(frames, ignore_index=True)
        out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
        # Ensure exactly our schema
        return out.reindex(columns=REQUIRED_COLS)


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)

