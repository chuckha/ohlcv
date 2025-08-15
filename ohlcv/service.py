from __future__ import annotations
from typing import Sequence, Dict, List, Tuple, DefaultDict
from collections import defaultdict
from datetime import date, timedelta
import logging
import pandas as pd

from .sql_store import SqlStore
from .provider_yf import YFProvider
from .calendar import sessions
from .utils import wide_to_tidy, tidy_to_wide, TIDY_COLS
from .errors import DataNotContiguous

log = logging.getLogger(__name__)

# Heuristics
YOUNG_THRESHOLD_DAYS = 365
EMPTY_SPAN_MIN_SESSIONS = 5
RECENT_BUFFER_SESSIONS = 2


def get_ohlcv_df(
    tickers: Sequence[str],
    start: date | str,
    end: date | str,
    *,
    store: SqlStore,
    provider: YFProvider,
    market: str = "NYSE",
    availability: str = "clip",
) -> pd.DataFrame:
    tks = [str(t).upper().strip() for t in tickers if str(t).strip()]
    s = pd.to_datetime(start).date() if not isinstance(start, date) else start
    e = pd.to_datetime(end).date() if not isinstance(end, date) else end

    sess = pd.to_datetime(sessions(s, e, market))
    sess = pd.DatetimeIndex(sess).tz_localize(None).normalize()

    # 1) Read local -> tidy -> MI aligned to sessions
    local_tidy = store.read_df(tks, s, e)
    local_mi = tidy_to_wide(local_tidy).reindex(sess)

    # 2) Initial gaps from local cache
    gaps = _find_mi_gaps(local_mi, tks, sess)

    # 3) Load symbol_meta and prune pre-IPO spans per ticker
    meta = store.get_meta(tks)
    span_to_tickers: DefaultDict[Tuple[date, date], List[str]] = defaultdict(list)

    for tkr, spans in gaps.items():
        if not spans:
            continue
        m = meta.get(tkr, {})
        eff_start = s
        # If we know a first_seen_date, don't fetch before it
        if m and m.get("first_seen_date"):
            try:
                fs = pd.to_datetime(m["first_seen_date"]).date()
                eff_start = max(eff_start, fs)
            except Exception:
                pass
        # If we've previously marked skip_before for this ticker, don't fetch at/before it
        if m and m.get("skip_before"):
            try:
                sb = pd.to_datetime(m["skip_before"]).date() + timedelta(days=1)
                eff_start = max(eff_start, sb)
            except Exception:
                pass

        # Clip or drop spans against eff_start
        for span_s, span_e in spans:
            if span_e < eff_start:
                continue  # entirely before effective window
            adj_s = max(span_s, eff_start)
            if adj_s <= span_e:
                span_to_tickers[(adj_s, span_e)].append(tkr)

    # 4) Fetch in MI batches per span; learn meta from results
    for (gs, ge), tlist in span_to_tickers.items():
        fetched_mi = provider.fetch_mi(tlist, gs, ge)
        if fetched_mi is None or fetched_mi.empty:
            # every ticker in tlist empty over this span; mark skip_before conservatively
            _maybe_mark_skip(store, tlist, gs, ge, sess)
            continue

        # Upsert tidy delta (only rows within [gs,ge])
        tidy = wide_to_tidy(fetched_mi)
        if tidy.empty:
            _maybe_mark_skip(store, tlist, gs, ge, sess)
            continue

        # Assign single-symbol UNKNOWN fallback if needed
        if len(tlist) == 1:
            if ("ticker" not in tidy.columns) or tidy["ticker"].eq("UNKNOWN").all():
                tidy.loc[:, "ticker"] = tlist[0]

        mask = (tidy["date"] >= pd.to_datetime(gs)) & (tidy["date"] <= pd.to_datetime(ge))
        tidy = tidy.loc[mask, TIDY_COLS]
        if not tidy.empty:
            store.upsert_df(tidy)
            # learn bounds
            store.upsert_bounds_from_df(tidy)

        # For tickers in this span that still had zero rows, consider advancing skip_before
        zero = _zero_tickers_in_fetch(fetched_mi, tlist)
        if zero:
            _maybe_mark_skip(store, zero, gs, ge, sess)

    # 5) Re-read final, pivot, contiguity (availability-aware)
    final_tidy = store.read_df(tks, s, e)
    final_mi = tidy_to_wide(final_tidy).reindex(sess)

    missing_after = _find_mi_gaps(final_mi, tks, sess)
    if availability == "clip" and missing_after:
        bounds = _mi_present_bounds(final_mi, tks)
        missing_after = _clip_mi_gaps(missing_after, bounds)

    # If a ticker has no present window at all, don't fail the batch
    remaining = {k: v for k, v in missing_after.items() if v} if missing_after else {}
    if remaining:
        raise DataNotContiguous(remaining)

    return final_mi


# --- helpers ---

def _zero_tickers_in_fetch(mi: pd.DataFrame, tlist: Sequence[str]) -> List[str]:
    out: List[str] = []
    for t in tlist:
        try:
            sub = mi.xs(t, axis=1, level=0, drop_level=False)
        except Exception:
            out.append(t)
            continue
        if sub.dropna(how="all").empty:
            out.append(t)
    return out


def _maybe_mark_skip(store: SqlStore, tickers: Sequence[str], gs: date, ge: date, sess: pd.DatetimeIndex) -> None:
    # Only mark skip for sufficiently long historical spans and not too close to today
    # span sessions count
    span_len = int(((sess >= pd.to_datetime(gs)) & (sess <= pd.to_datetime(ge))).sum())
    if span_len < EMPTY_SPAN_MIN_SESSIONS:
        return
    if len(sess) >= RECENT_BUFFER_SESSIONS and pd.to_datetime(ge) > sess.max() - pd.Timedelta(days=RECENT_BUFFER_SESSIONS*2):
        # simple guard: don't mark if ge is very close to most recent session
        return
    for t in tickers:
        store.advance_skip_before(t, ge)

def _find_mi_gaps(mi: pd.DataFrame, tickers: Sequence[str], sess: pd.DatetimeIndex) -> Dict[str, List[Tuple[date, date]]]:
    gaps: Dict[str, List[Tuple[date, date]]] = {}
    # When MI, columns are like (field, ticker) or (ticker, field) depending on pivot order.
    # Our tidy_to_wide produced: level0=field, level1=ticker
    if not isinstance(mi.columns, pd.MultiIndex) or mi.empty:
        return {t: [(sess[0].date(), sess[-1].date())] for t in tickers} if len(sess) else {}

    # define a function to get a Series of 'present' boolean per ticker based on Close
    def present_series(t: str) -> pd.Series:
        # columns order from tidy_to_wide: (field, ticker)
        try:
            s = mi["close", t]
        except Exception:
            # fallback: any of open/high/low/close
            cols = [c for c in [("open", t),("high", t),("low", t),("close", t)] if c in mi.columns]
            if not cols:
                return pd.Series([False]*len(sess), index=sess)
            s = mi[cols].bfill(axis=1).iloc[:,0]
        return s.notna().reindex(sess, fill_value=False)

    for t in tickers:
        pres = present_series(t)
        if pres.all():
            continue
        miss_dates = sess[~pres]
        if len(miss_dates) == 0:
            continue
        # coalesce to spans
        spans = _coalesce_by_session_index(miss_dates, sess)
        gaps[t] = spans
    return gaps


def _mi_present_bounds(mi: pd.DataFrame, tickers: Sequence[str]) -> Dict[str, Tuple[date | None, date | None]]:
    bounds: Dict[str, Tuple[date | None, date | None]] = {t: (None, None) for t in tickers}
    if mi is None or mi.empty:
        return bounds
    # using close level
    if isinstance(mi.columns, pd.MultiIndex) and ("close" in mi.columns.get_level_values(0)):
        close = mi["close"]
        for t in close.columns:
            s = close[t].dropna()
            if s.empty: continue
            bounds[str(t)] = (s.index[0].date(), s.index[-1].date())
    return bounds


def _clip_mi_gaps(gaps: Dict[str, List[Tuple[date, date]]], bounds: Dict[str, Tuple[date | None, date | None]]):
    clipped: Dict[str, List[Tuple[date, date]]] = {}
    for t, spans in gaps.items():
        dmin, dmax = bounds.get(t, (None, None))
        if dmin is None and dmax is None:
            clipped[t] = spans
            continue
        kept: List[Tuple[date, date]] = []
        for s, e in spans:
            # drop leading/trailing parts outside [dmin,dmax]
            if dmin is not None and e < dmin:  # entirely before
                continue
            if dmax is not None and s > dmax:  # entirely after
                continue
            ns = max(s, dmin) if dmin is not None else s
            ne = min(e, dmax) if dmax is not None else e
            if ns <= ne:
                kept.append((ns, ne))
        if kept:
            clipped[t] = kept
    return clipped

def _coalesce_by_session_index(miss_dates: pd.DatetimeIndex, sess: pd.DatetimeIndex):
    if len(miss_dates) == 0:
        return []
    pos = pd.Index(sess)  # map each session date to its index position
    miss_pos = sorted(pos.get_indexer(miss_dates))  # positions of missing sessions
    spans = []
    start_i = prev_i = miss_pos[0]
    for i in miss_pos[1:]:
        if i == prev_i + 1:           # consecutive in the sessions index
            prev_i = i
        else:
            spans.append((sess[start_i].date(), sess[prev_i].date()))
            start_i = prev_i = i
    spans.append((sess[start_i].date(), sess[prev_i].date()))
    return spans
