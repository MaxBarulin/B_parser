"""Reconstruct Polymarket-style UP/DOWN outcomes from 5m OHLC bars.

Two conventions supported:
- "candle"     : UP if close > open in the same bar (matches typical
                  "next 5 min up/down" prediction markets where the
                  window is wall-clock-aligned with the candle)
- "close_diff" : UP if close[t] > close[t-1] (rolling 5-min window)

Ties (close == reference) are conventionally resolved as DOWN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def reconstruct(klines: pd.DataFrame, rule: str = "candle") -> pd.DataFrame:
    df = klines.sort_values("open_time").reset_index(drop=True).copy()

    if rule == "candle":
        df["outcome"] = np.where(df["close"] > df["open"], "UP", "DOWN")
    elif rule == "close_diff":
        df["prev_close"] = df["close"].shift(1)
        df = df.dropna(subset=["prev_close"]).reset_index(drop=True)
        df["outcome"] = np.where(df["close"] > df["prev_close"], "UP", "DOWN")
    else:
        raise ValueError(f"Unknown rule: {rule!r} (use 'candle' or 'close_diff')")

    return df[["open_time", "close_time", "open", "close", "outcome"]]
