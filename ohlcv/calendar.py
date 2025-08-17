from __future__ import annotations
from datetime import date
from typing import List
import pandas as pd
import pandas_market_calendars as mcal
from functools import lru_cache


def sessions(start: date, end: date, market: str = "XNYS") -> List[date]:
    if end < start:
        return []
    cal = mcal.get_calendar(market)
    sched = cal.schedule(start_date=start, end_date=end)
    return list(sched.index.date)


@lru_cache(maxsize=64)
def _sessions_index_cached(market: str, start_iso: str, end_iso: str) -> pd.DatetimeIndex:
    start = pd.to_datetime(start_iso).date()
    end = pd.to_datetime(end_iso).date()
    if end < start:
        return pd.DatetimeIndex([])
    cal = mcal.get_calendar(market)
    sched = cal.schedule(start_date=start, end_date=end)
    return pd.DatetimeIndex(sched.index).tz_localize(None).normalize()


def sessions_index(start: date, end: date, market: str = "XNYS") -> pd.DatetimeIndex:
    """Return trading sessions for (market,start,end) with process-level caching.

    Using an internal cached variant avoids recomputing holidays/valid_days for every
    ticker when many share the same market (e.g., 800 tickers on XNYS).
    """
    return _sessions_index_cached(market, start.isoformat(), end.isoformat())
