"""Binance Spot klines (api).

Used for reconstructing Polymarket UP/DOWN outcomes (close[t] vs close[t-1]).
Same payload shape as futures, different host.
"""
from __future__ import annotations

import pandas as pd

from ._http import get_json, interval_to_ms

BASE = "https://api.binance.com"
MAX_LIMIT = 1000  # spot endpoint caps at 1000

_RAW_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]
_NUM_COLS = [
    "open", "high", "low", "close", "volume",
    "quote_volume", "taker_buy_base", "taker_buy_quote",
]


def _fetch_batch(symbol: str, interval: str, start_ms: int, end_ms: int):
    return get_json(
        f"{BASE}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        },
    )


def fetch_klines(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step_ms = interval_to_ms(interval)

    rows: list = []
    cursor = start_ms
    while cursor <= end_ms:
        batch = _fetch_batch(symbol, interval, cursor, end_ms)
        if not batch:
            break
        rows.extend(batch)
        last_open = batch[-1][0]
        cursor = last_open + step_ms
        if len(batch) < MAX_LIMIT:
            break

    if not rows:
        return pd.DataFrame(columns=[c for c in _RAW_COLS if c != "ignore"])

    df = pd.DataFrame(rows, columns=_RAW_COLS).drop(columns=["ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df["trades"] = df["trades"].astype("int64")
    for c in _NUM_COLS:
        df[c] = pd.to_numeric(df[c])
    return df
