from __future__ import annotations
from typing import Dict

# Simple suffix → pandas‑market‑calendars ID map
_SUFFIX_TO_CAL: Dict[str, str] = {
    ".TO": "XTSE",  # Toronto
    ".AX": "XASX",  # Australia
    # add more as needed, e.g.:
    # ".L":  "XLON",  # London
    # ".PA": "XPAR",  # Paris
}

DEFAULT_CAL = "NYSE"

def calendar_for_ticker(ticker: str, overrides: Dict[str, str] | None = None) -> str:
    t = str(ticker).upper().strip()
    if overrides and t in overrides:
        return overrides[t]
    for suf, cal in _SUFFIX_TO_CAL.items():
        if t.endswith(suf):
            return cal
    return DEFAULT_CAL
