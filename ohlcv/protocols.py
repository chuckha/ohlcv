from __future__ import annotations
from typing import Protocol, runtime_checkable, Sequence
from datetime import date
import pandas as pd

@runtime_checkable
class Store(Protocol):
    """Local DB boundary: *no business logic*.

    Expected DataFrame schema (long/tidy):
    columns = ["ticker", "date", "open", "high", "low", "close", "volume"]
    - ticker: str
    - date: datetime64[ns] or date (normalized to session date)
    - price columns: float
    - volume: int
    """
    def read_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame: ...
    def upsert_df(self, df: pd.DataFrame) -> None: ...  # idempotent on (ticker,date)


@runtime_checkable
class Provider(Protocol):
    """External data source. Returns the same schema as Store.read_df."""
    def fetch_df(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame: ...
