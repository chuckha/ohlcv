# ohlcv/calendar.py
from __future__ import annotations
from datetime import date
from typing import List, Optional
import pandas_market_calendars as mcal

def sessions(start: date, end: date, market: str = "NYSE") -> List[date]:
    if end < start:
        return []
    cal = mcal.get_calendar(market)
    sched = cal.schedule(start_date=start, end_date=end)
    return list(sched.index.date)
