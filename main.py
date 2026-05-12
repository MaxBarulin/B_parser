"""CLI for the data layer.

Usage:
  python main.py download --start 2025-12-18 --end 2025-12-19 --sources binance_futures
  python main.py download                          # use period from config.yaml
  python main.py status                            # show cached ranges per source

Sources: binance_futures, binance_spot, bybit_linear, binance_aggtrades, all
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from data import (
    binance_aggtrades,
    binance_futures,
    binance_spot,
    bybit,
    storage,
)

ALL_SOURCES = ["binance_futures", "binance_spot", "bybit_linear", "binance_aggtrades"]


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def parse_ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def _klines_download(
    source: str,
    fetcher,
    symbol: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: str,
) -> None:
    path = storage.cache_path(cache_dir, source, symbol, interval)
    cached_max = storage.cached_max_ts(path, "open_time")
    step = pd.Timedelta(interval)

    if cached_max is not None:
        actual_start = max(start, cached_max + step)
    else:
        actual_start = start

    if actual_start > end:
        print(f"[{source}] cache up-to-date (max {cached_max})")
        return

    print(f"[{source}] fetching {actual_start} -> {end}")
    df = fetcher(symbol, interval, actual_start, end)
    merged = storage.merge_save(df, path, key="open_time")
    rows = 0 if merged is None else len(merged)
    print(f"[{source}] cached rows: {rows} -> {path}")


def _aggtrades_download(
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: str,
) -> None:
    source = "binance_aggtrades_5m"
    days = list(binance_aggtrades.daterange(start, end))
    total = len(days)
    done = skipped = failed = 0
    for i, day in enumerate(days, 1):
        out = storage.daily_cache_path(cache_dir, source, symbol, day.isoformat())
        if out.exists():
            skipped += 1
            continue
        print(f"[{source}] {i}/{total}  {day}  downloading...", flush=True)
        try:
            agg = binance_aggtrades.fetch_day_5m(symbol, day)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[{source}] {day} FAILED: {e}")
            continue
        storage.save(agg, out)
        done += 1
        print(f"[{source}] {i}/{total}  {day}  ok ({len(agg)} buckets)", flush=True)
    print(f"[{source}] summary: done={done} skipped(cached)={skipped} failed={failed}")


def cmd_download(args, cfg) -> None:
    symbol = cfg["symbol"]
    interval = cfg["interval"]
    cache_dir = cfg["cache_dir"]

    start = parse_ts(args.start) if args.start else parse_ts(cfg["period"]["start"])
    end = parse_ts(args.end) if args.end else parse_ts(cfg["period"]["end"])

    if args.sources == ["all"]:
        sources = ALL_SOURCES
    else:
        sources = args.sources

    if "binance_futures" in sources:
        _klines_download("binance_futures", binance_futures.fetch_klines, symbol, interval, start, end, cache_dir)
    if "binance_spot" in sources:
        _klines_download("binance_spot", binance_spot.fetch_klines, symbol, interval, start, end, cache_dir)
    if "bybit_linear" in sources:
        _klines_download("bybit_linear", bybit.fetch_klines, symbol, interval, start, end, cache_dir)
    if "binance_aggtrades" in sources:
        _aggtrades_download(symbol, start, end, cache_dir)


def cmd_status(_args, cfg) -> None:
    symbol = cfg["symbol"]
    interval = cfg["interval"]
    cache_dir = cfg["cache_dir"]

    for src in ["binance_futures", "binance_spot", "bybit_linear"]:
        p = storage.cache_path(cache_dir, src, symbol, interval)
        df = storage.load(p)
        if df is None or df.empty:
            print(f"[{src}] empty")
            continue
        print(f"[{src}] rows={len(df)}  {df['open_time'].min()} -> {df['open_time'].max()}")

    agg_dir = Path(cache_dir) / "binance_aggtrades_5m" / symbol
    if agg_dir.exists():
        files = sorted(agg_dir.glob("*.parquet"))
        print(f"[binance_aggtrades_5m] daily files: {len(files)}  ({files[0].stem if files else '-'} .. {files[-1].stem if files else '-'})")
    else:
        print("[binance_aggtrades_5m] empty")


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="b_parser")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dl = sub.add_parser("download", help="Download/refresh data")
    p_dl.add_argument("--start", help="UTC start (e.g. 2025-12-18 or 2025-12-18T00:00:00Z)")
    p_dl.add_argument("--end", help="UTC end")
    p_dl.add_argument(
        "--sources",
        nargs="+",
        default=["all"],
        choices=ALL_SOURCES + ["all"],
        help="One or more sources to download",
    )
    p_dl.set_defaults(func=cmd_download)

    p_st = sub.add_parser("status", help="Show cached ranges per source")
    p_st.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args, cfg)


if __name__ == "__main__":
    main()
