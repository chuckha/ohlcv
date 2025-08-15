from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Sequence
import os

from .protocols import Store, Provider
from .sql_store import SqlStore
from .provider_yf import YFProvider
from .service import get_ohlcv_df as _get_ohlcv_df

@dataclass
class OhlcvClient:
    store: Store
    provider: Provider
    market: str = "NYSE"
    availability: str = "clip"  # "strict" | "clip"

    def get_df(self, tickers: Sequence[str], start: date | str, end: date | str):
        return _get_ohlcv_df(
            tickers, start, end,
            store=self.store,
            provider=self.provider,
            include_partial=False,
            market=self.market,
            availability=self.availability,
        )

_default_client: OhlcvClient | None = None

def configure(*, dsn: str | None = None, sql_dir: str | None = None, market: str | None = None, auto_adjust: bool = False, availability: str | None = None) -> None:
    global _default_client
    dsn = dsn or os.getenv("LIGHTQL_DATABASE_URL") or "sqlite:///./data/database.sqlite3"
    sql_dir = sql_dir or os.getenv("OHLCV_SQL_DIR", "sql")
    market = market or os.getenv("OHLCV_MARKET", "NYSE")
    availability = (availability or os.getenv("OHLCV_AVAILABILITY", "clip")).lower()
    if availability not in {"clip", "strict"}:
        availability = "clip"
    store = SqlStore(dsn=dsn, sql_dir=sql_dir)
    provider = YFProvider(auto_adjust=auto_adjust)
    _default_client = OhlcvClient(store=store, provider=provider, market=market, availability=availability)


def get_ohlcv_df(tickers: Sequence[str], start: date | str, end: date | str):
    from .client import _default_client as _dc  # local import to avoid cycle in editors
    if _dc is None:
        configure()
        from .client import _default_client as _dc2  # re-read
        return _dc2.get_df(tickers, start, end)  # type: ignore
    return _dc.get_df(tickers, start, end)  # type: ignore
