"""Binance USDT-M Futures aggTrades — daily zip files from data.binance.vision.

Daily files are large (often 100-500 MB compressed). We stream into memory,
aggregate to 5-min buckets immediately, persist only the aggregate.

URL pattern:
  https://data.binance.vision/data/futures/um/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY-MM-DD}.zip

Buyer-is-maker semantics (Binance):
  is_buyer_maker == True  -> aggressive side is SELL (taker sold)
  is_buyer_maker == False -> aggressive side is BUY  (taker bought)
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

import pandas as pd

from ._http import get_bytes

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"

# Standard column schema (we rename by position regardless of source header).
COLS = ["agg_id", "price", "qty", "first_id", "last_id", "ts", "is_buyer_maker"]


def _url(symbol: str, day: date) -> str:
    return f"{BASE}/{symbol}/{symbol}-aggTrades-{day.isoformat()}.zip"


def _read_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = z.namelist()[0]
        raw = z.read(name)

    peek = raw[:64].decode("utf-8", errors="ignore").lstrip()
    has_header = bool(peek) and not peek[0].isdigit() and peek[0] != "-"

    df = pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        dtype={0: "int64", 5: "int64"},
    )
    df.columns = COLS  # normalize by position
    return df


def aggregate_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse raw aggTrades into 5-minute buckets."""
    if df.empty:
        return pd.DataFrame(
            columns=[
                "bucket", "trades", "total_qty", "total_quote",
                "buy_aggressive_qty", "sell_aggressive_qty",
                "buy_aggressive_quote", "sell_aggressive_quote",
                "max_trade_qty", "avg_trade_qty",
            ]
        )

    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["bucket"] = df["ts"].dt.floor("5min")
    df["quote"] = df["price"] * df["qty"]

    # is_buyer_maker -> aggressive sell; else aggressive buy
    aggressive_buy = ~df["is_buyer_maker"].astype(bool)
    df["buy_qty"] = df["qty"].where(aggressive_buy, 0.0)
    df["sell_qty"] = df["qty"].where(~aggressive_buy, 0.0)
    df["buy_quote"] = df["quote"].where(aggressive_buy, 0.0)
    df["sell_quote"] = df["quote"].where(~aggressive_buy, 0.0)

    g = df.groupby("bucket", sort=True)
    agg = g.agg(
        trades=("agg_id", "count"),
        total_qty=("qty", "sum"),
        total_quote=("quote", "sum"),
        buy_aggressive_qty=("buy_qty", "sum"),
        sell_aggressive_qty=("sell_qty", "sum"),
        buy_aggressive_quote=("buy_quote", "sum"),
        sell_aggressive_quote=("sell_quote", "sum"),
        max_trade_qty=("qty", "max"),
        avg_trade_qty=("qty", "mean"),
    ).reset_index()
    return agg


def fetch_day_5m(symbol: str, day: date) -> pd.DataFrame:
    """Download one daily aggTrades zip and return 5-min aggregate."""
    content = get_bytes(_url(symbol, day), desc=f"{symbol} {day}")
    raw = _read_zip(content)
    return aggregate_5m(raw)


def daterange(start: pd.Timestamp, end: pd.Timestamp):
    d = start.date()
    last = end.date()
    while d <= last:
        yield d
        d += timedelta(days=1)
