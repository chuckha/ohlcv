from __future__ import annotations
from typing import Sequence, Dict, List, Tuple, DefaultDict
from collections import defaultdict
from datetime import date, timedelta
import logging
import pandas as pd

from .sql_store import SqlStore
from .provider_yf import YFProvider
from .calendar import sessions_index
from .utils import wide_to_tidy, tidy_to_wide, TIDY_COLS
from .errors import DataNotContiguous
from .market_resolver import calendar_for_ticker

log = logging.getLogger(__name__)

# existing heuristics kept as‑is
YOUNG_THRESHOLD_DAYS = 365
EMPTY_SPAN_MIN_SESSIONS = 10
RECENT_BUFFER_SESSIONS = 5


def get_ohlcv_df(
    tickers: Sequence[str],
    start: date | str,
    end: date | str,
    *,
    store: SqlStore,
    provider: YFProvider,
    market_overrides: Dict[str, str] | None = None,  # optional per‑ticker override
    availability: str = "clip",
) -> pd.DataFrame:
    tks = [str(t).upper().strip() for t in tickers if str(t).strip()]
    s = pd.to_datetime(start).date() if not isinstance(start, date) else start
    e = pd.to_datetime(end).date() if not isinstance(end, date) else end

    # 0) Build **per‑ticker** session indices
    sess_by_ticker: Dict[str, pd.DatetimeIndex] = {
        t: sessions_index(s, e, calendar_for_ticker(t, overrides=market_overrides)) for t in tks
    }
    # Union index for the returned MI (visual alignment only)
    union_idx = _union_indexes(list(sess_by_ticker.values()))

    # 1) Read local → tidy → MI and align to **union** (display)
    local_tidy = store.read_df(tks, s, e)  # tidy
    local_mi = tidy_to_wide(local_tidy).reindex(union_idx)

    # 2) Find gaps **per ticker using that ticker's sessions**
    gaps = _find_mi_gaps_per_ticker(local_mi, tks, sess_by_ticker)

    # 3) Load symbol_meta and prune spans per‑ticker (pre‑IPO/stop_after handled elsewhere)
    from .sql_store import SqlStore as _S  # type hint only
    meta = store.get_meta(tks) if hasattr(store, "get_meta") else {t: {} for t in tks}

    span_to_tickers: DefaultDict[Tuple[date, date], List[str]] = defaultdict(list)
    for tkr, spans in gaps.items():
        if not spans:
            continue
        # Effective window per ticker (head/tail guards)
        eff_start, eff_end = _effective_window_for_ticker(tkr, s, e, meta, sess_by_ticker[tkr])
        if eff_end < eff_start:
            continue
        for span_s, span_e in spans:
            if span_e < eff_start or span_s > eff_end:
                continue
            adj_s = max(span_s, eff_start)
            adj_e = min(span_e, eff_end)
            if adj_s <= adj_e:
                span_to_tickers[(adj_s, adj_e)].append(tkr)

    # 4) Fetch batches per (span_s, span_e)
    for (gs, ge), tlist in span_to_tickers.items():
        fetched_mi = provider.fetch_mi(tlist, gs, ge)
        if fetched_mi is None or fetched_mi.empty:
            _maybe_mark_skip(store, tlist, gs, ge, union_idx)
            _maybe_mark_stop_after(store, tlist, gs, ge, union_idx)
            continue
        tidy = wide_to_tidy(fetched_mi)
        if tidy.empty:
            _maybe_mark_skip(store, tlist, gs, ge, union_idx)
            _maybe_mark_stop_after(store, tlist, gs, ge, union_idx)
            continue
        if len(tlist) == 1 and ("ticker" not in tidy.columns or tidy["ticker"].eq("UNKNOWN").all()):
            tidy.loc[:, "ticker"] = tlist[0]
        mask = (tidy["date"] >= pd.to_datetime(gs)) & (tidy["date"] <= pd.to_datetime(ge))
        tidy = tidy.loc[mask, TIDY_COLS]
        if not tidy.empty:
            store.upsert_df(tidy)
            if hasattr(store, "upsert_bounds_from_df"):
                store.upsert_bounds_from_df(tidy)

        zero = _zero_tickers_in_fetch(fetched_mi, tlist)
        if zero:
            _maybe_mark_skip(store, zero, gs, ge, union_idx)
            _maybe_mark_stop_after(store, zero, gs, ge, union_idx)

    # 5) Final read → MI aligned to union; contiguity per ticker sessions
    final_tidy = store.read_df(tks, s, e)
    final_mi = tidy_to_wide(final_tidy).reindex(union_idx)

    missing_after = _find_mi_gaps_per_ticker(final_mi, tks, sess_by_ticker)
    if availability == "clip" and missing_after:
        bounds = _mi_present_bounds(final_mi, tks)
        missing_after = _clip_mi_gaps_per_ticker(missing_after, bounds)

    remaining = {k: v for k, v in missing_after.items() if v} if missing_after else {}
    if remaining:
        raise DataNotContiguous(remaining)

    # Return MI aligned on union (so the shape is stable across tickers)
    return final_mi


# ---- Per‑ticker gap detection helpers ----

def _union_indexes(indexes: List[pd.DatetimeIndex]) -> pd.DatetimeIndex:
    if not indexes:
        return pd.DatetimeIndex([])
    out = indexes[0]
    for idx in indexes[1:]:
        out = out.union(idx)
    return out


def _present_series(mi: pd.DataFrame, ticker: str) -> pd.Series:
    # Our MI orientation is (field, ticker). Prefer 'close', fallback to any OHLC.
    if isinstance(mi.columns, pd.MultiIndex):
        if ("close", ticker) in mi.columns:
            s = mi["close", ticker]
        else:
            cols = [c for c in [("open", ticker), ("high", ticker), ("low", ticker), ("close", ticker)] if c in mi.columns]
            if not cols:
                return pd.Series([False] * len(mi.index), index=mi.index)
            s = mi[cols].bfill(axis=1).iloc[:, 0]
        return s.notna()
    # No MI columns → treat as entirely missing for this helper
    return pd.Series([False] * len(mi.index), index=mi.index)


def _coalesce_by_session_index(miss_dates: pd.DatetimeIndex, sess: pd.DatetimeIndex) -> List[Tuple[date, date]]:
    if len(miss_dates) == 0:
        return []
    # positions of missing sessions within sess
    pos = sess.get_indexer(miss_dates)
    pos = [p for p in pos if p >= 0]
    if not pos:
        return []
    pos.sort()
    spans: List[Tuple[date, date]] = []
    start_i = prev_i = pos[0]
    for i in pos[1:]:
        if i == prev_i + 1:
            prev_i = i
        else:
            spans.append((sess[start_i].date(), sess[prev_i].date()))
            start_i = prev_i = i
    spans.append((sess[start_i].date(), sess[prev_i].date()))
    return spans


def _find_mi_gaps_per_ticker(mi: pd.DataFrame, tickers: Sequence[str], sess_by_ticker: Dict[str, pd.DatetimeIndex]) -> Dict[str, List[Tuple[date, date]]]:
    gaps: Dict[str, List[Tuple[date, date]]] = {}
    for t in tickers:
        sess = sess_by_ticker.get(t, pd.DatetimeIndex([]))
        if len(sess) == 0:
            gaps[t] = []
            continue
        pres = _present_series(mi, t).reindex(sess, fill_value=False)
        if pres.all():
            continue
        miss_dates = sess[~pres]
        gaps[t] = _coalesce_by_session_index(miss_dates, sess)
    return gaps


def _clip_mi_gaps_per_ticker(gaps: Dict[str, List[Tuple[date, date]]], bounds: Dict[str, Tuple[date | None, date | None]]):
    clipped: Dict[str, List[Tuple[date, date]]] = {}
    for t, spans in gaps.items():
        dmin, dmax = bounds.get(t, (None, None))
        if dmin is None and dmax is None:
            continue
        kept: List[Tuple[date, date]] = []
        for s, e in spans:
            if dmin is not None and e < dmin:
                continue
            if dmax is not None and s > dmax:
                continue
            ns = max(s, dmin) if dmin is not None else s
            ne = min(e, dmax) if dmax is not None else e
            if ns <= ne:
                kept.append((ns, ne))
        if kept:
            clipped[t] = kept
    return clipped


def _effective_window_for_ticker(tkr: str, req_s: date, req_e: date, meta: Dict[str, Dict[str, str | None]], sess: pd.DatetimeIndex) -> Tuple[date, date]:
    eff_start, eff_end = req_s, req_e
    m = meta.get(tkr, {}) if meta else {}
    if m.get("first_seen_date"):
        try:
            eff_start = max(eff_start, pd.to_datetime(m["first_seen_date"]).date())
        except Exception:
            pass
    if m.get("skip_before"):
        try:
            eff_start = max(eff_start, (pd.to_datetime(m["skip_before"]).date() + timedelta(days=1)))
        except Exception:
            pass
    if m.get("stop_after"):
        try:
            eff_end = min(eff_end, pd.to_datetime(m["stop_after"]).date())
        except Exception:
            pass
    elif m.get("last_seen_date"):
        try:
            lsd = pd.to_datetime(m["last_seen_date"]).date()
            # default: do not probe past last_seen here; your global tail probe env can be integrated if desired
            eff_end = min(eff_end, lsd)
        except Exception:
            pass
    # Also clamp effective window to existing session range for safety
    if len(sess):
        eff_start = max(eff_start, sess.min().date())
        eff_end = min(eff_end, sess.max().date())
    return eff_start, eff_end

def _mi_present_bounds(mi: pd.DataFrame, tickers: Sequence[str]) -> Dict[str, Tuple[date | None, date | None]]:
    """Compute first/last present dates per ticker from a MultiIndex-wide frame.

    Prefers the 'close' field when available; otherwise falls back to any OHLC field.
    Returns (None, None) for tickers with no prints at all.
    """
    bounds: Dict[str, Tuple[date | None, date | None]] = {str(t): (None, None) for t in tickers}
    if mi is None or mi.empty or not isinstance(mi.columns, pd.MultiIndex):
        return bounds

    level0 = mi.columns.get_level_values(0)

    # Preferred: use close
    if "close" in level0:
        close = mi["close"]
        for t in close.columns:
            s = close[t].dropna()
            if not s.empty:
                bounds[str(t)] = (s.index[0].date(), s.index[-1].date())
        # Ensure all requested tickers are present in dict
        for t in tickers:
            if str(t) not in bounds:
                bounds[str(t)] = (None, None)
        return bounds

    # Fallback: use any of open/high/low/close
    fields = ["open", "high", "low", "close"]
    for t in tickers:
        cols = [c for c in [(f, t) for f in fields] if c in mi.columns]
        if not cols:
            continue
        s = mi[cols].bfill(axis=1).iloc[:, 0].dropna()
        if not s.empty:
            bounds[str(t)] = (s.index[0].date(), s.index[-1].date())

    return bounds

def _zero_tickers_in_fetch(mi: pd.DataFrame, tlist: Sequence[str]) -> List[str]:
    """Return tickers from *tlist* that have no actual data in *mi*.

    Works for MI columns (level0=ticker, level1=fields) and the flat single‑ticker
    case that yfinance sometimes returns. Treats a ticker as "zero" if **all**
    values across known OHLCV fields are NaN/empty.
    """
    out: List[str] = []
    if mi is None or mi.empty:
        return list(tlist)

    if isinstance(mi.columns, pd.MultiIndex) and mi.columns.nlevels >= 2:
        for t in tlist:
            try:
                sub = mi.xs(t, axis=1, level=0, drop_level=False)
            except Exception:
                out.append(t)
                continue
            if sub.dropna(how="all").empty:
                out.append(t)
        return out

    # Flat frame (likely single ticker)
    if len(tlist) == 1:
        cols = [c for c in [
            "Open","High","Low","Close","Adj Close","Volume",
            "open","high","low","close","volume"
        ] if c in mi.columns]
        if not cols or mi[cols].dropna(how="all").empty:
            out.append(tlist[0])
    return out
