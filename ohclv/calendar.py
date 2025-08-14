from __future__ import annotations
from datetime import date, timedelta
from typing import List

def sessions(start: date, end: date) -> List[date]:
    """Return naive trading sessions between start and end (inclusive).

    Minimal default: weekdays only (Mon-Fri). Extend or swap with a real market
    calendar as needed.
    """
    if end < start:
        return []
    cur = start
    out: List[date] = []
    one = timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:  # 0=Mon..4=Fri
            out.append(cur)
        cur += one
    return out

