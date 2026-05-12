"""Tiny HTTP wrapper with retry/backoff for exchange REST."""
from __future__ import annotations

import time

import requests


def get_json(url: str, params: dict | None = None, timeout: int = 30, retries: int = 4):
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == retries - 1:
                break
            time.sleep(2 ** attempt)
    assert last_err is not None
    raise last_err


def get_bytes(url: str, timeout: int = 120, retries: int = 4) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == retries - 1:
                break
            time.sleep(2 ** attempt)
    assert last_err is not None
    raise last_err


_UNITS_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}


def interval_to_ms(interval: str) -> int:
    """Convert e.g. '5m', '1h', '1d' to milliseconds."""
    return int(interval[:-1]) * _UNITS_MS[interval[-1]]
