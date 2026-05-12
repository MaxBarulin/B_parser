"""Feature engineering for each martingale signal.

For each signal (= moment when 3 same-direction outcomes just completed)
we compute features evaluated AT the close of the 3rd trigger candle.
These are the features used to test the customer's hypothesis: long
series are preceded by breakouts, volume spikes, taker imbalance,
expanded range etc.

Notation: a "5m bar" is one row of the klines df. Lookback windows
are LEFT-EXCLUSIVE of the current bar (i.e., the "30m lookback" at
bar T covers T-30m .. T-5m, NOT including T itself), otherwise the
breakout check would be trivially true.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Window sizes expressed in 5-minute bars
WINDOWS = {
    "30m": 6,
    "60m": 12,
    "3h": 36,
    "9h": 108,
    "24h": 288,
    "7d": 2016,
}


def _enrich_klines(klines: pd.DataFrame) -> pd.DataFrame:
    """Add rolling/derived columns to klines (vectorised, single pass)."""
    k = klines.sort_values("open_time").set_index("open_time").copy()

    # Prior-window extremes (shift(1) excludes the current bar itself)
    high_prev = k["high"].shift(1)
    low_prev = k["low"].shift(1)
    for name, win in WINDOWS.items():
        k[f"prior_high_{name}"] = high_prev.rolling(win, min_periods=win).max()
        k[f"prior_low_{name}"]  = low_prev.rolling(win, min_periods=win).min()

    # Per-bar structure
    k["range"] = k["high"] - k["low"]
    k["body"] = (k["close"] - k["open"]).abs()
    k["body_to_range"] = np.where(k["range"] > 0, k["body"] / k["range"], 0.0)
    k["close_position"] = np.where(
        k["range"] > 0, (k["close"] - k["low"]) / k["range"], 0.5
    )

    # Prior 60m averages (lookback, excluding current bar)
    k["vol_60m_avg_prior"] = k["volume"].shift(1).rolling(12, min_periods=12).mean()
    k["range_60m_avg_prior"] = k["range"].shift(1).rolling(12, min_periods=12).mean()

    # 3-bar trigger aggregates ending at this bar (incl. current = the 3rd candle)
    k["vol_3bar_sum"] = k["volume"].rolling(3, min_periods=3).sum()
    k["range_3bar"] = k["high"].rolling(3, min_periods=3).max() - k["low"].rolling(3, min_periods=3).min()
    k["body_to_range_3bar_avg"] = k["body_to_range"].rolling(3, min_periods=3).mean()
    k["close_position_3bar_avg"] = k["close_position"].rolling(3, min_periods=3).mean()

    # Taker imbalance (klines come with taker_buy_base when source is Binance)
    if "taker_buy_base" in k.columns:
        k["taker_buy_3bar_sum"] = k["taker_buy_base"].rolling(3, min_periods=3).sum()
        k["taker_buy_ratio_3bar"] = k["taker_buy_3bar_sum"] / k["vol_3bar_sum"]

    # Trend distance
    k["ema20"] = k["close"].ewm(span=20, adjust=False).mean()

    # Daily UTC VWAP (resets at 00:00 UTC)
    k["volume_quote"] = k["close"] * k["volume"]
    day = k.index.tz_convert("UTC").date
    by_day = pd.Series(day, index=k.index)
    k["cum_vol_day"] = k["volume"].groupby(by_day).cumsum()
    k["cum_quote_day"] = k["volume_quote"].groupby(by_day).cumsum()
    k["vwap"] = k["cum_quote_day"] / k["cum_vol_day"]

    # Forward returns from current bar's close
    k["close_15m_fwd"] = k["close"].shift(-3)   # 3 bars later (15 min)
    k["close_60m_fwd"] = k["close"].shift(-12)  # 12 bars later (60 min)

    return k


def add_features(signals: pd.DataFrame, klines: pd.DataFrame) -> pd.DataFrame:
    """Attach feature columns to each signal row.

    Features are evaluated at the 3rd trigger candle (= series_start_time + 10m).
    """
    if signals.empty:
        return signals.copy()

    k = _enrich_klines(klines)

    # 3rd trigger candle timestamp for each signal
    third_t = (signals["series_start_time"] + pd.Timedelta(minutes=10)).values
    third = k.reindex(pd.DatetimeIndex(third_t, tz="UTC"))

    out = signals.copy().reset_index(drop=True)
    third = third.reset_index(drop=True)
    third_close = third["close"].values

    # --- Breakouts (close of 3rd bar vs prior window extremes) ---
    # Stored as float (0.0/1.0/NaN) so NaN propagates for rows where the
    # lookback window doesn't fit (early start of data).
    for name in WINDOWS:
        ph = third[f"prior_high_{name}"].to_numpy(dtype=float)
        pl = third[f"prior_low_{name}"].to_numpy(dtype=float)
        bh = np.where(np.isnan(ph), np.nan, (third_close > ph).astype(float))
        bl = np.where(np.isnan(pl), np.nan, (third_close < pl).astype(float))
        out[f"breakout_{name}_high"] = bh
        out[f"breakout_{name}_low"] = bl
        out[f"breakout_{name}_with_series"] = np.where(
            out["direction"].to_numpy() == "UP", bh, bl,
        )

    # --- Volume ---
    out["volume_3bar_sum"] = third["vol_3bar_sum"].values
    out["volume_60m_avg_prior"] = third["vol_60m_avg_prior"].values
    # 3 trigger bars vs 3x the per-bar 60m prior mean
    denom = 3 * out["volume_60m_avg_prior"]
    out["volume_ratio"] = np.where(denom > 0, out["volume_3bar_sum"] / denom, np.nan)

    # --- Taker imbalance ---
    if "taker_buy_ratio_3bar" in third.columns:
        out["taker_buy_ratio_3bar"] = third["taker_buy_ratio_3bar"].values
        out["taker_sell_ratio_3bar"] = 1.0 - out["taker_buy_ratio_3bar"]
        # imbalance in the SAME direction as the series (the dangerous case)
        out["taker_with_series_ratio"] = np.where(
            out["direction"] == "UP",
            out["taker_buy_ratio_3bar"],
            out["taker_sell_ratio_3bar"],
        )
    else:
        out["taker_buy_ratio_3bar"] = np.nan
        out["taker_sell_ratio_3bar"] = np.nan
        out["taker_with_series_ratio"] = np.nan

    # --- Candle structure of 3rd bar + avg of 3 ---
    out["body_to_range_3rd"] = third["body_to_range"].values
    out["close_position_3rd"] = third["close_position"].values
    out["body_to_range_3bar_avg"] = third["body_to_range_3bar_avg"].values
    out["close_position_3bar_avg"] = third["close_position_3bar_avg"].values

    # --- Volatility / range expansion ---
    out["range_3bar"] = third["range_3bar"].values
    out["range_60m_avg_prior"] = third["range_60m_avg_prior"].values
    denom_r = 3 * out["range_60m_avg_prior"]
    out["range_expansion"] = np.where(denom_r > 0, out["range_3bar"] / denom_r, np.nan)

    # --- Trend distance ---
    out["ema20"] = third["ema20"].values
    out["vwap"] = third["vwap"].values
    out["distance_from_ema20_pct"] = np.where(
        third["ema20"].values > 0,
        (third_close - third["ema20"].values) / third["ema20"].values * 100.0,
        np.nan,
    )
    out["distance_from_vwap_pct"] = np.where(
        third["vwap"].values > 0,
        (third_close - third["vwap"].values) / third["vwap"].values * 100.0,
        np.nan,
    )

    # --- Forward returns from entry (= close of 3rd bar ≈ open of 4th bar) ---
    fwd15 = third["close_15m_fwd"].values
    fwd60 = third["close_60m_fwd"].values
    out["fwd_return_15m_pct"] = np.where(third_close > 0, (fwd15 / third_close - 1.0) * 100.0, np.nan)
    out["fwd_return_60m_pct"] = np.where(third_close > 0, (fwd60 / third_close - 1.0) * 100.0, np.nan)

    return out


def long_series_context(series: pd.DataFrame, klines: pd.DataFrame, threshold: int = 7) -> pd.DataFrame:
    """One row per long series (length >= threshold) with feature columns.

    Matches the customer's File 2 (long_series_exchange_context.xlsx) layout.
    """
    s = series[series["length"] >= threshold].copy().reset_index(drop=True)
    if s.empty:
        return s

    k = _enrich_klines(klines)
    first_t = pd.DatetimeIndex(s["start_time"], tz="UTC")
    third_t = pd.DatetimeIndex(s["start_time"] + pd.Timedelta(minutes=10), tz="UTC")
    end_t = pd.DatetimeIndex(s["start_time"] + pd.to_timedelta(s["length"] * 5 - 5, unit="m"), tz="UTC")

    first = k.reindex(first_t).reset_index(drop=True)
    third = k.reindex(third_t).reset_index(drop=True)
    last = k.reindex(end_t).reset_index(drop=True)

    s["start_msk"] = s["start_time"].dt.tz_convert("Europe/Moscow")
    s["end_msk"]   = s["end_time"].dt.tz_convert("Europe/Moscow")

    s["return_during_series_pct"] = (last["close"].values / first["open"].values - 1.0) * 100.0
    s["volume_during_series"] = np.nan  # filled below per row (variable length)

    # Variable-length aggregates per series (3-bar context already on `third`)
    s["volume_ratio_first_3bar"] = np.where(
        third["vol_60m_avg_prior"].values > 0,
        third["vol_3bar_sum"].values / (3 * third["vol_60m_avg_prior"].values),
        np.nan,
    )
    s["range_expansion_first_3bar"] = np.where(
        third["range_60m_avg_prior"].values > 0,
        third["range_3bar"].values / (3 * third["range_60m_avg_prior"].values),
        np.nan,
    )
    if "taker_buy_ratio_3bar" in third.columns:
        s["taker_buy_ratio_first_3bar"] = third["taker_buy_ratio_3bar"].values
        s["taker_sell_ratio_first_3bar"] = 1.0 - s["taker_buy_ratio_first_3bar"]

    third_close = third["close"].to_numpy(dtype=float)
    for name in ("60m", "3h", "24h"):
        ph = third[f"prior_high_{name}"].to_numpy(dtype=float)
        pl = third[f"prior_low_{name}"].to_numpy(dtype=float)
        bh = np.where(np.isnan(ph), np.nan, (third_close > ph).astype(float))
        bl = np.where(np.isnan(pl), np.nan, (third_close < pl).astype(float))
        s[f"breakout_{name}_before_series"] = np.where(
            s["direction"].to_numpy() == "UP", bh, bl,
        )

    return s
