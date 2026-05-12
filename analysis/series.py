"""Detect consecutive runs of same-direction outcomes and label martingale signals.

Strategy under test:
  - When 3 same-direction outcomes occur in a row -> bet OPPOSITE direction
  - Martingale chain: up to `max_attempts` retries (each on the next candle)
  - Win  = direction breaks within `max_attempts` (series length <= 3 + max_attempts - 1)
  - Loss = series length >= 3 + max_attempts  (e.g. 6+ for max_attempts=3)
  - "Long series" (the failure mode we want to detect/avoid) = length >= long_threshold (7)
"""
from __future__ import annotations

import pandas as pd


def detect_series(outcomes: pd.DataFrame) -> pd.DataFrame:
    """One row per maximal run of identical outcomes."""
    df = outcomes.sort_values("open_time").reset_index(drop=True).copy()
    df["series_id"] = (df["outcome"] != df["outcome"].shift(1)).cumsum()

    g = df.groupby("series_id", sort=True)
    out = g.agg(
        direction=("outcome", "first"),
        length=("outcome", "size"),
        start_time=("open_time", "first"),
        end_time=("close_time", "last"),
        start_open=("open", "first"),
        end_close=("close", "last"),
    ).reset_index(drop=True)

    out["return_pct"] = (out["end_close"] / out["start_open"] - 1.0) * 100.0
    return out


def generate_signals(
    outcomes: pd.DataFrame,
    max_attempts: int = 3,
    long_threshold: int = 7,
) -> pd.DataFrame:
    """One signal per series of length >= 3.

    The 'signal' is the moment we'd place our first bet (opposite direction)
    after seeing 3 same-direction outcomes. We then simulate up to
    `max_attempts` martingale retries and record the outcome.
    """
    df = outcomes.sort_values("open_time").reset_index(drop=True)

    out_arr = df["outcome"].to_numpy()
    open_time = df["open_time"].to_numpy()
    close_time = df["close_time"].to_numpy()
    open_px = df["open"].to_numpy()
    close_px = df["close"].to_numpy()
    n = len(df)

    rows: list[dict] = []
    i = 0
    loss_len = 3 + max_attempts  # series length at which we definitively lose

    while i <= n - 3:
        if not (out_arr[i] == out_arr[i + 1] == out_arr[i + 2]):
            i += 1
            continue

        direction = out_arr[i]
        j = i + 3
        while j < n and out_arr[j] == direction:
            j += 1
        length = j - i

        # If the run reaches the end of data without breaking and the win was
        # still possible, outcome is indeterminate — skip.
        if j == n and length < loss_len:
            i = j
            continue

        if length < loss_len:
            result = "win"
            win_attempt = length - 2  # length 3->1, 4->2, 5->3 (for max_attempts=3)
        else:
            result = "loss"
            win_attempt = None

        rows.append({
            "signal_open_time": open_time[i + 3] if i + 3 < n else pd.NaT,
            "series_start_time": open_time[i],
            "third_candle_close_time": close_time[i + 2],
            "direction": direction,
            "bet_direction": "DOWN" if direction == "UP" else "UP",
            "series_start_open": float(open_px[i]),
            "third_candle_close": float(close_px[i + 2]),
            "final_series_length": int(length),
            "result": result,
            "win_attempt": win_attempt,
            "is_long_series": length >= long_threshold,
        })

        # Skip past the entire series (we don't re-trigger inside the same run)
        i = j

    return pd.DataFrame(rows)


def summarize(series: pd.DataFrame, signals: pd.DataFrame) -> dict:
    """Compact stats for printing to console."""
    return {
        "n_outcomes_up": None,  # caller can fill from outcomes df
        "n_series": int(len(series)),
        "max_series_len": int(series["length"].max()) if len(series) else 0,
        "n_series_ge7": int((series["length"] >= 7).sum()),
        "n_series_ge10": int((series["length"] >= 10).sum()),
        "n_signals": int(len(signals)),
        "n_wins": int((signals["result"] == "win").sum()),
        "n_losses": int((signals["result"] == "loss").sum()),
        "win_rate": float((signals["result"] == "win").mean()) if len(signals) else 0.0,
    }
