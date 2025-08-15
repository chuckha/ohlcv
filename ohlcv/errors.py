from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

@dataclass
class DataNotContiguous(Exception):
    """Raised when we cannot return a contiguous dataset for requested sessions.

    missing maps ticker -> list of (start_date, end_date) *session* spans that could not be filled.
    """
    missing: Dict[str, List[Tuple[object, object]]]

    def __str__(self) -> str:
        parts = []
        for tkr, spans in self.missing.items():
            pieces = ", ".join(f"{s}..{e}" for s, e in spans)
            parts.append(f"{tkr}: [{pieces}]")
        return "DataNotContiguous: " + "; ".join(parts)


class ProviderError(Exception):
    pass
