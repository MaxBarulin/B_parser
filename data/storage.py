"""Parquet cache with idempotent merge by timestamp key."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def cache_path(cache_dir: str | Path, source: str, symbol: str, interval: str) -> Path:
    base = Path(cache_dir) / source / f"{symbol}_{interval}"
    base.mkdir(parents=True, exist_ok=True)
    return base / "data.parquet"


def daily_cache_path(cache_dir: str | Path, source: str, symbol: str, date: str) -> Path:
    base = Path(cache_dir) / source / symbol
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{date}.parquet"


def load(path: str | Path) -> pd.DataFrame | None:
    p = Path(path)
    if not p.exists():
        return None
    return pd.read_parquet(p)


def save(df: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="snappy", index=False)


def merge_save(df_new: pd.DataFrame, path: str | Path, key: str) -> pd.DataFrame:
    """Append df_new to cached parquet, dedupe by key, sort, persist."""
    if df_new is None or df_new.empty:
        existing = load(path)
        return existing if existing is not None else df_new

    existing = load(path)
    if existing is not None and not existing.empty:
        combined = pd.concat([existing, df_new], ignore_index=True)
    else:
        combined = df_new

    combined = (
        combined.drop_duplicates(subset=[key], keep="last")
        .sort_values(key)
        .reset_index(drop=True)
    )
    save(combined, path)
    return combined


def cached_max_ts(path: str | Path, key: str) -> pd.Timestamp | None:
    df = load(path)
    if df is None or df.empty:
        return None
    return df[key].max()
