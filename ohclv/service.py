from __future__ import annotations
from typing import Iterable, Sequence, Dict, List, Tuple
from datetime import date, datetime
import pandas as pd

from .protocols import Store, Provider
from .calendar import sessions
from .errors import DataNotContiguous

Schema = List[str]
REQUIRED_COLS: Schema = ["ticker", "date", "open", "high", "low", "close", "volume"]


def get_ohlcv_df(
    tickers: Sequence[str],
    start: date | str,
    end: date | str,
    *,
    store: Store,
    provider: Provider,
    include_partial: bool = False,
) -> pd.DataFrame:
    """Local-first OHLCV fetch with gap fill, returning a contiguous daily DataFrame.

    Parameters
    ----------
    tickers : list[str]
        Symbols to fetch. Duplicates ignored, case-insensitive.
    start, end : date | str
        Session date range (inclusive). Strings parsed as YYYY-MM-DD.
    store : Store
        Local repository (read/upsert only).
    provider : Provider
        Remote source for gap fills.
    include_partial : bool
        If True, return whatever is available after best-effort fill; otherwise
        raise DataNotContiguous when gaps remain.
    """
    tks = _normalize_tickers(tickers)
    s, e = _normalize_dates(start, end)
    expected = sessions(s, e)

    # 1) Read what's present
    df0 = store.read_df(tks, s, e)
    df0 = _normalize_df(df0)

    # 2) Compute gaps per ticker
    gaps = _find_gaps(df0, tks, expected)

    # 3) Fetch + upsert missing spans
    for tkr, spans in gaps.items():
        for span_s, span_e in spans:
            fetched = provider.fetch_df([tkr], span_s, span_e)
            fetched = _normalize_df(fetched)
            if not fetched.empty:
                store.upsert_df(fetched)

    # 4) Re-read final
    final = store.read_df(tks, s, e)
    final = _normalize_df(final)

    # 5) Validate / trim to expected sessions
    missing_after = _find_gaps(final, tks, expected)
    if missing_after and not include_partial:
        raise DataNotContiguous(missing_after)

    # Keep only expected sessions & requested tickers
    if not final.empty:
        final = final[final["date"].isin(pd.to_datetime(expected))]
        final = final[final["ticker"].isin(tks)]
        final = final.sort_values(["ticker", "date"]).reset_index(drop=True)

    return final


# -----------------
# helpers (private)
# -----------------

def _normalize_tickers(tickers: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for t in (t.upper().strip() for t in tickers):
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    if not out:
        raise ValueError("No tickers provided")
    return out


def _normalize_dates(start: date | str, end: date | str) -> Tuple[date, date]:
    s = _to_date(start)
    e = _to_date(end)
    if e < s:
        raise ValueError("end < start")
    return s, e


def _to_date(x: date | str) -> date:
    if isinstance(x, date):
        return x
    return datetime.strptime(str(x), "%Y-%m-%d").date()


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return _empty_df()
    if df.empty:
        return _empty_df()
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing columns: {missing}")
    out = df.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper()
    # ensure date is datetime64[ns]
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    # light type coercions (non-strict)
    for c in ["open", "high", "low", "close"]:
        out[c] = out[c].astype(float)
    out["volume"] = out["volume"].astype("int64", errors="ignore") if hasattr(out["volume"], "astype") else out["volume"]
    return out[REQUIRED_COLS]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)


def _find_gaps(df: pd.DataFrame, tickers: Sequence[str], expected: Sequence[date]) -> Dict[str, List[Tuple[date, date]]]:
    """Return ticker -> list of missing (start,end) session spans.

    Uses the provided *expected* sessions list as ground truth, so holidays
    (if any) must be excluded there.
    """
    exp_idx = pd.to_datetime(expected)
    present: Dict[str, set] = {t: set() for t in tickers}
    if not df.empty:
        # normalize to date-only for comparison
        tmp = df[["ticker", "date"]].copy()
        tmp["date"] = pd.to_datetime(tmp["date"]).dt.normalize()
        for t, grp in tmp.groupby("ticker"):
            present.setdefault(t, set()).update(set(grp["date"].unique()))

    gaps: Dict[str, List[Tuple[date, date]]] = {}
    exp_list = list(pd.to_datetime(expected))
    for t in tickers:
        miss = [d for d in exp_list if d not in present.get(t, set())]
        if not miss:
            continue
        spans: List[Tuple[date, date]] = []
        # merge consecutive expected dates into spans
        start = miss[0]
        prev = miss[0]
        for d in miss[1:]:
            if (d - prev).days == 1:  # consecutive calendar day; safe because expected excludes weekends/holidays
                prev = d
            else:
                spans.append((start.date(), prev.date()))
                start = prev = d
        spans.append((start.date(), prev.date()))
        gaps[t] = spans
    return gaps
