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
from analysis import outcomes as outcomes_mod
from analysis import series as series_mod

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


def _concat_aggtrades(cache_dir: str, symbol: str) -> pd.DataFrame | None:
    agg_dir = Path(cache_dir) / "binance_aggtrades_5m" / symbol
    if not agg_dir.exists():
        return None
    files = sorted(agg_dir.glob("*.parquet"))
    if not files:
        return None
    parts = [pd.read_parquet(f) for f in files]
    return pd.concat(parts, ignore_index=True).sort_values("bucket").reset_index(drop=True)


def _write_excel(df: pd.DataFrame, path: Path) -> None:
    """Excel cannot store tz-aware timestamps; strip tz (data is UTC, document it)."""
    df = df.copy()
    for col in df.select_dtypes(include=["datetimetz"]).columns:
        df[col] = df[col].dt.tz_convert("UTC").dt.tz_localize(None)
    df.to_excel(path, index=False, engine="openpyxl")


def cmd_export(args, cfg) -> None:
    symbol = cfg["symbol"]
    interval = cfg["interval"]
    cache_dir = cfg["cache_dir"]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format  # 'xlsx' or 'csv'

    def _dump(name: str, df: pd.DataFrame | None) -> None:
        if df is None or df.empty:
            print(f"[export] {name}: empty, skipped")
            return
        ext = "xlsx" if fmt == "xlsx" else "csv"
        out = out_dir / f"{name}.{ext}"
        if fmt == "xlsx":
            _write_excel(df, out)
        else:
            df.to_csv(out, index=False, sep=args.csv_sep)
        print(f"[export] {name}: {len(df)} rows -> {out}")

    for src in ["binance_futures", "binance_spot", "bybit_linear"]:
        p = storage.cache_path(cache_dir, src, symbol, interval)
        _dump(f"{src}_{symbol}_{interval}", storage.load(p))

    _dump(f"binance_aggtrades_5m_{symbol}", _concat_aggtrades(cache_dir, symbol))

    # analysis artefacts (one set per source)
    analysis_root = Path(cache_dir) / "analysis"
    if analysis_root.exists():
        for src_dir in sorted(analysis_root.iterdir()):
            if not src_dir.is_dir():
                continue
            for kind in ("outcomes", "series", "signals"):
                p = src_dir / f"{kind}.parquet"
                if p.exists():
                    _dump(f"analysis_{src_dir.name}_{kind}", pd.read_parquet(p))


def cmd_analyze(args, cfg) -> None:
    symbol = cfg["symbol"]
    interval = cfg["interval"]
    cache_dir = cfg["cache_dir"]
    src = args.source

    p = storage.cache_path(cache_dir, src, symbol, interval)
    klines = storage.load(p)
    if klines is None or klines.empty:
        print(f"[analyze] no cached klines for {src}; run `download` first")
        return

    print(f"[analyze] source={src} rule={args.outcome_rule} max_attempts={args.max_attempts}")
    outcomes = outcomes_mod.reconstruct(klines, rule=args.outcome_rule)
    series = series_mod.detect_series(outcomes)
    signals = series_mod.generate_signals(
        outcomes,
        max_attempts=args.max_attempts,
        long_threshold=args.long_threshold,
    )

    out_dir = Path(cache_dir) / "analysis" / src
    out_dir.mkdir(parents=True, exist_ok=True)
    storage.save(outcomes, out_dir / "outcomes.parquet")
    storage.save(series, out_dir / "series.parquet")
    storage.save(signals, out_dir / "signals.parquet")

    n_up = int((outcomes["outcome"] == "UP").sum())
    n_down = int((outcomes["outcome"] == "DOWN").sum())
    stats = series_mod.summarize(series, signals)

    print(f"  outcomes : {len(outcomes)}  UP={n_up}  DOWN={n_down}  (UP rate {n_up/len(outcomes):.1%})")
    print(f"  series   : total={stats['n_series']}  max_len={stats['max_series_len']}  "
          f">=7: {stats['n_series_ge7']}  >=10: {stats['n_series_ge10']}")
    print(f"  signals  : total={stats['n_signals']}  wins={stats['n_wins']}  "
          f"losses={stats['n_losses']}  win_rate={stats['win_rate']:.1%}")
    if stats["n_signals"]:
        loss_share = stats["n_losses"] / stats["n_signals"]
        # expected value at fair odds (each win pays at 1:1 of cumulative martingale stake; loss eats it):
        # this is just a quick sanity number — real backtest comes in step 4
        print(f"  long-series share of signals (>=7): "
              f"{int(signals['is_long_series'].sum())} ({signals['is_long_series'].mean():.1%})")
        _ = loss_share  # silenced — real PnL in backtest step
    print(f"  saved    -> {out_dir}")


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

    p_ex = sub.add_parser("export", help="Export cache to Excel/CSV")
    p_ex.add_argument("--out", default="export", help="Output directory (default: ./export)")
    p_ex.add_argument(
        "--format", default="xlsx", choices=["xlsx", "csv"],
        help="Output format (default: xlsx)",
    )
    p_ex.add_argument(
        "--csv-sep", default=";",
        help="CSV separator (default: ';' for RU Excel; use ',' for international)",
    )
    p_ex.set_defaults(func=cmd_export)

    p_an = sub.add_parser("analyze", help="Reconstruct UP/DOWN, detect series, label martingale signals")
    p_an.add_argument(
        "--source", default="binance_spot",
        choices=["binance_spot", "binance_futures", "bybit_linear"],
        help="Klines source to use (default: binance_spot, closest to Polymarket resolution)",
    )
    p_an.add_argument(
        "--outcome-rule", default="candle", choices=["candle", "close_diff"],
        help="'candle' = close>open in same bar; 'close_diff' = close[t]>close[t-1]",
    )
    p_an.add_argument(
        "--max-attempts", type=int, default=3,
        help="Number of martingale bets after the 3-in-a-row trigger (default: 3)",
    )
    p_an.add_argument(
        "--long-threshold", type=int, default=7,
        help="Series length considered 'long' to flag (default: 7)",
    )
    p_an.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    args.func(args, cfg)


if __name__ == "__main__":
    main()
