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
    market: str = "NYSE",                 # <-- default explicit market
    availability: str = "clip",           # <-- "strict" | "clip"
) -> pd.DataFrame:
    """Local-first OHLCV fetch with gap fill, returning a contiguous daily DataFrame.

    availability:
      - "strict": require contiguity across the full [start,end] for each ticker
      - "clip":   ignore leading/trailing gaps outside each ticker's present window
                   (still strict about mid-window gaps)
    """
    tks = _normalize_tickers(tickers)
    s, e = _normalize_dates(start, end)
    base_expected = sessions(s, e, market)  # session dates for the market

    # 1) Read what's present
    df0 = store.read_df(tks, s, e)
    df0 = _normalize_df(df0)

    # 2) Compute gaps per ticker (strict expectations initially)
    gaps = _find_gaps(df0, tks, base_expected)

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

    # 5) Validate contiguity. If availability==clip, ignore pre/post-listing gaps.
    missing_after = _find_gaps(final, tks, base_expected)

    if availability == "clip" and missing_after:
        # Determine present windows per ticker from what we *actually* have
        present_bounds = _present_bounds(final, tks)
        # Build per-ticker expected sessions clipped to present window
        expected_by = {
            t: [d for d in base_expected if _in_present_window(d, present_bounds.get(t), s, e)]
            for t in tks
        }
        # Recompute gaps against clipped expectations
        missing_after = _find_gaps_per_ticker(final, tks, expected_by)

    if missing_after and not include_partial:
        raise DataNotContiguous(missing_after)

    # Keep only expected sessions (strict base); returning extra days is confusing
    if not final.empty:
        final = final[final["date"].isin(pd.to_datetime(base_expected))]
        final = final[final["ticker"].isin(tks)]
        final = final.sort_values(["ticker", "date"]).reset_index(drop=True)

    return final

# -----------------
# helpers (private)
# -----------------

def _present_bounds(df: pd.DataFrame, tickers: Sequence[str]) -> Dict[str, Tuple[date | None, date | None]]:
    """Return each ticker's (min_date, max_date) present in df (date objects)."""
    out: Dict[str, Tuple[date | None, date | None]] = {t: (None, None) for t in tickers}
    if df.empty:
        return out
    agg = df.groupby("ticker")["date"].agg(["min", "max"]).reset_index()
    for _, row in agg.iterrows():
        t = str(row["ticker"]).upper()
        dmin = pd.to_datetime(row["min"]).date() if pd.notna(row["min"]) else None
        dmax = pd.to_datetime(row["max"]).date() if pd.notna(row["max"]) else None
        out[t] = (dmin, dmax)
    return out


def _in_present_window(d: date, bounds: Tuple[date | None, date | None] | None, s: date, e: date) -> bool:
    if not bounds:
        return True  # unknown → keep strict; gaps will remain if truly missing
    dmin, dmax = bounds
    # Clip only leading/trailing gaps: if we have at least one row, restrict to [dmin, dmax]
    if dmin is not None and d < dmin:
        return False
    if dmax is not None and d > dmax:
        return False
    return True


def _find_gaps(df: pd.DataFrame, tickers: Sequence[str], expected: Sequence[date]) -> Dict[str, List[Tuple[date, date]]]:
    exp_list = list(pd.to_datetime(expected))
    present: Dict[str, set] = {t: set() for t in tickers}
    if not df.empty:
        tmp = df[["ticker", "date"]].copy()
        tmp["date"] = pd.to_datetime(tmp["date"]).dt.normalize()
        for t, grp in tmp.groupby("ticker"):
            present.setdefault(str(t).upper(), set()).update(set(grp["date"].unique()))

    gaps: Dict[str, List[Tuple[date, date]]] = {}
    for t in tickers:
        have = present.get(t, set())
        miss = [d for d in exp_list if d not in have]
        if not miss:
            continue
        spans: List[Tuple[date, date]] = []
        start = miss[0]
        prev = miss[0]
        for d in miss[1:]:
            if (d - prev).days == 1:
                prev = d
            else:
                spans.append((start.date(), prev.date()))
                start = prev = d
        spans.append((start.date(), prev.date()))
        gaps[str(t).upper()] = spans
    return gaps


def _find_gaps_per_ticker(df: pd.DataFrame, tickers: Sequence[str], expected_by: Dict[str, List[date]]) -> Dict[str, List[Tuple[date, date]]]:
    present: Dict[str, set] = {t: set() for t in tickers}
    if not df.empty:
        tmp = df[["ticker", "date"]].copy()
        tmp["date"] = pd.to_datetime(tmp["date"]).dt.normalize()
        for t, grp in tmp.groupby("ticker"):
            present.setdefault(str(t).upper(), set()).update(set(grp["date"].unique()))

    gaps: Dict[str, List[Tuple[date, date]]] = {}
    for t in tickers:
        exp_list = list(pd.to_datetime(expected_by.get(t, [])))
        if not exp_list:
            continue  # no expectations for this ticker after clipping
        have = present.get(t, set())
        miss = [d for d in exp_list if d not in have]
        if not miss:
            continue
        spans: List[Tuple[date, date]] = []
        start = miss[0]
        prev = miss[0]
        for d in miss[1:]:
            if (d - prev).days == 1:
                prev = d
            else:
                spans.append((start.date(), prev.date()))
                start = prev = d
        spans.append((start.date(), prev.date()))
        gaps[str(t).upper()] = spans
    return gaps


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
