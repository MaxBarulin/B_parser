"""Bybit V5 klines (category=linear by default).

Endpoint: GET /v5/market/kline
- limit max 1000
- IMPORTANT: response is in DESCENDING order
- interval is minutes as string ("5", "15", "60") or "D"/"W"/"M"
"""
from __future__ import annotations

import pandas as pd

from ._http import get_json

BASE = "https://api.bybit.com"
MAX_LIMIT = 1000

_COLS = ["open_time", "open", "high", "low", "close", "volume", "turnover"]
_NUM_COLS = ["open", "high", "low", "close", "volume", "turnover"]


def _to_bybit_interval(interval: str) -> str:
    """'5m' -> '5'; '1h' -> '60'; '1d' -> 'D'."""
    if interval.endswith("m"):
        return interval[:-1]
    if interval.endswith("h"):
        return str(int(interval[:-1]) * 60)
    if interval.endswith("d"):
        return "D"
    raise ValueError(f"Unsupported interval for Bybit: {interval}")


def _interval_ms(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1]) * 60_000
    if interval.endswith("h"):
        return int(interval[:-1]) * 3_600_000
    if interval.endswith("d"):
        return int(interval[:-1]) * 86_400_000
    raise ValueError(interval)


def _fetch_batch(symbol: str, interval: str, start_ms: int, end_ms: int, category: str):
    data = get_json(
        f"{BASE}/v5/market/kline",
        params={
            "category": category,
            "symbol": symbol,
            "interval": _to_bybit_interval(interval),
            "start": start_ms,
            "end": end_ms,
            "limit": MAX_LIMIT,
        },
    )
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit error: {data}")
    return data["result"]["list"]


def fetch_klines(
    symbol: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    category: str = "linear",
) -> pd.DataFrame:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step_ms = _interval_ms(interval)

    rows: list = []
    cursor = start_ms
    while cursor <= end_ms:
        batch = _fetch_batch(symbol, interval, cursor, end_ms, category)
        if not batch:
            break
        batch.reverse()  # bybit returns DESC
        rows.extend(batch)
        last_open = int(batch[-1][0])
        cursor = last_open + step_ms
        if len(batch) < MAX_LIMIT:
            break

    if not rows:
        return pd.DataFrame(columns=_COLS)

    df = pd.DataFrame(rows, columns=_COLS)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    for c in _NUM_COLS:
        df[c] = pd.to_numeric(df[c])
    return df
