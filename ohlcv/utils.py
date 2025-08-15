from __future__ import annotations
import pandas as pd

TIDY_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]

def wide_to_tidy(mi_df: pd.DataFrame) -> pd.DataFrame:
    if mi_df is None or mi_df.empty:
        return pd.DataFrame(columns=TIDY_COLS)

    df = mi_df.copy()

    # ---- Multi-ticker (MultiIndex columns) path ----
    if isinstance(df.columns, pd.MultiIndex) and df.columns.nlevels >= 2:
        lvl1 = df.columns.get_level_values(1)

        # Drop non-price helper columns from yfinance (e.g., "Repaired?")
        drop_mask = (lvl1 == "Repaired?")
        if drop_mask.any():
            df = df.drop(columns=df.columns[drop_mask])
            lvl1 = df.columns.get_level_values(1)

        # Prefer raw Close; drop Adj Close if both exist
        if ("Close" in lvl1) and ("Adj Close" in lvl1):
            df = df.drop(columns=df.columns[df.columns.get_level_values(1) == "Adj Close"])
        elif ("Close" not in lvl1) and ("Adj Close" in lvl1):
            # Promote Adj Close -> Close
            df = df.rename(columns=lambda s: ("Close" if s == "Adj Close" else s), level=1)

        long = df.stack(level=0, future_stack=True)  # index -> (date, ticker)
        long.index = long.index.set_names(["date", "ticker"])
        long = long.reset_index()

        long = long.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Date": "date",
            "Datetime": "date",
        })
        out = long

    else:
        # ---- Single-ticker (flat columns) path ----
        out = df.reset_index()
        if "Date" in out.columns:     out = out.rename(columns={"Date": "date"})
        if "Datetime" in out.columns: out = out.rename(columns={"Datetime": "date"})
        ren = {"Open":"open","High":"high","Low":"low","Volume":"volume"}
        if "Close" in out.columns:        ren["Close"] = "close"
        elif "Adj Close" in out.columns:  ren["Adj Close"] = "close"
        out = out.rename(columns=ren)
        out["ticker"] = "UNKNOWN"

    # Only keep tidy columns we recognize
    out = out.loc[:, [c for c in TIDY_COLS if c in out.columns]].copy()

    # Normalize types
    out.loc[:, "ticker"] = out.get("ticker", pd.Series(dtype=str)).astype(str).str.upper()
    out.loc[:, "date"] = pd.to_datetime(out.get("date"), errors="coerce").dt.tz_localize(None).dt.normalize()

    for c in ["open", "high", "low", "close"]:
        if c in out.columns:
            out.loc[:, c] = pd.to_numeric(out[c], errors="coerce")
    if "volume" in out.columns:
        out.loc[:, "volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype("int64")

    # Drop rows missing core OHLC
    need = [c for c in ["open","high","low","close"] if c in out.columns]
    if need:
        out = out.dropna(subset=need).copy()

    return out.reindex(columns=TIDY_COLS)

def tidy_to_wide(tidy: pd.DataFrame) -> pd.DataFrame:
    if tidy is None or tidy.empty:
        return pd.DataFrame()
    df = tidy.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    wide = df.pivot(index="date", columns="ticker", values=["open","high","low","close","volume"])  # type: ignore[arg-type]
    return wide.sort_index(axis=1)
