"""Public facade for the OHLCV skeleton.

You get a single entry point: ``get_ohlcv_df``.

Example
-------
>>> from ohlcv import get_ohlcv_df
>>> from ohlcv.protocols import Store, Provider
>>> # provide concrete Store/Provider implementations elsewhere
>>> df = get_ohlcv_df(["KOS", "ATEC"], "2025-01-01", "2025-03-31", store=my_store, provider=my_provider)
"""
from .service import get_ohlcv_df
from .errors import DataNotContiguous, ProviderError
from . import protocols

__all__ = ["get_ohlcv_df", "DataNotContiguous", "ProviderError", "protocols"]

