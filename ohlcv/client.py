from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Sequence
import os
import pandas as pd

from .sql_store import SqlStore
from .provider_yf import YFProvider
from .service import get_ohlcv_df as _get_ohlcv_df
from .resources import unpack_sql_package
from .schema import ensure_schema


@dataclass
class OhlcvClient:
    store: SqlStore
    provider: YFProvider
    market: str = "NYSE"
    availability: str = "clip"

    def get_df(self, tickers: Sequence[str], start: date | str, end: date | str):
        return _get_ohlcv_df(
            tickers, start, end,
            store=self.store,
            provider=self.provider,
            market=self.market,
            availability=self.availability,
        )


_default_client: OhlcvClient | None = None


def configure(*, dsn: str | None = None, market: str | None = None, availability: str | None = None) -> None:
    """Configure the default client.

    - Loads packaged SQL/migrations.
    - Auto-applies forward-only migrations on the target DB.
    - No `sql_dir` in public API anymore.
    """
    global _default_client
    dsn = dsn or os.getenv("LIGHTQL_DATABASE_URL") or "sqlite:///./data/database.sqlite3"
    market = (market or os.getenv("OHLCV_MARKET", "NYSE")).upper()
    availability = (availability or os.getenv("OHLCV_AVAILABILITY", "clip")).lower()
    if availability not in {"clip", "strict"}: availability = "clip"

    sql_root = unpack_sql_package()
    ensure_schema(dsn, sql_root)

    store = SqlStore(dsn=dsn)
    provider = YFProvider(auto_adjust=False)
    _default_client = OhlcvClient(store=store, provider=provider, market=market, availability=availability)


def _ensure_default_client() -> OhlcvClient:
    global _default_client
    if _default_client is None:
        configure()
    return _default_client  # type: ignore[return-value]


def get_ohlcv_df(tickers: Sequence[str], start: date | str, end: date | str):
    client = _ensure_default_client()
    return client.get_df(tickers, start, end)
