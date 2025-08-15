from __future__ import annotations
from datetime import date, timedelta
from typing import Sequence
import logging
import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

class _DropYFMissing(logging.Filter):
    NEEDLES = ("YFPricesMissingError", "Failed download")
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try: msg = record.getMessage()
        except Exception: return True
        return not any(n in msg for n in self.NEEDLES)


class YFProvider:
    """yfinance Provider that returns MultiIndex-wide frames.

    columns: MultiIndex(levels=[tickers, fields]) with fields in [Open,High,Low,Close,Volume]
    index: DatetimeIndex (UTC-naive, normalized)
    """
    def __init__(self, *, auto_adjust: bool = False, quiet_missing: bool = True):
        if auto_adjust:
            raise ValueError("Store policy: only raw OHLCV allowed; set auto_adjust=False")
        self.quiet_missing = quiet_missing
        self._yf_logger = logging.getLogger("yfinance")

    def fetch_mi(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        tks = [str(t).upper().strip() for t in tickers if str(t).strip()]
        if not tks:
            return pd.DataFrame()
        # yfinance end is exclusive; widen to reduce boundary gaps
        yf_start = start - timedelta(days=2)
        yf_end   = end + timedelta(days=2)

        flt = _DropYFMissing() if self.quiet_missing else None
        if flt: self._yf_logger.addFilter(flt)
        try:
            log.info(f"Tickers {tks} from {yf_start.isoformat()} to {yf_end.isoformat()}")
            df = yf.download(
                tickers=tks,
                start=yf_start.isoformat(),
                end=yf_end.isoformat(),
                interval="1d",
                auto_adjust=False,
                repair=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        finally:
            if flt:
                try: self._yf_logger.removeFilter(flt)
                except Exception: pass
        if df is None or len(df) == 0:
            return pd.DataFrame()
        # Ensure normalized index
        df = df.copy()
        idx = pd.to_datetime(df.index, errors="coerce").tz_localize(None).normalize()
        df.index = idx
        return df
