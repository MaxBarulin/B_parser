"""Семь графиков из пункта 11 ТЗ заказчика (File 4).

Все диаграммы — barplots / histogram, всё на русском, сохраняются в PNG
в указанной папке. Использует matplotlib c backend='Agg' (без GUI),
поэтому работает headless и из PyInstaller .exe.

Графики:
  1. stop_rate_by_hour_msk.png         — доля проигрышей по часам МСК
  2. stop_rate_by_volume_bucket.png    — доля проигрышей по группам volume_ratio
  3. stop_rate_by_taker_bucket.png     — доля проигрышей по группам taker imbalance
  4. stop_rate_breakout_vs_no.png      — доля проигрышей: с пробоем vs без
  5. pnl_by_3h_window_msk.png          — PnL по 3-часовым окнам МСК
  6. pnl_by_6h_window_msk.png          — PnL по 6-часовым окнам МСК
  7. long_series_length_distribution.png — гистограмма длин серий 7+
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt


def _setup_style():
    plt.rcParams.update({
        "figure.figsize": (9, 5),
        "figure.dpi": 110,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 10,
    })


def _save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{name}.png"
    fig.tight_layout()
    fig.savefig(p, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return p


def chart_stop_rate_by_hour(signals: pd.DataFrame, out_dir: Path) -> Path:
    if "hour_msk" not in signals.columns:
        return None
    g = signals.groupby("hour_msk")["result"].agg(
        total="count",
        losses=lambda x: (x == "loss").sum(),
    )
    g["stop_rate_%"] = g["losses"] / g["total"] * 100.0

    fig, ax = plt.subplots()
    bars = ax.bar(g.index.astype(int), g["stop_rate_%"], color="#cc4444")
    ax.set_xlabel("Час (МСК)")
    ax.set_ylabel("Доля проигрышей, %")
    ax.set_title("Доля проигрышей по часам (МСК)")
    ax.set_xticks(range(24))
    ax.axhline(g["stop_rate_%"].mean(), color="black", linestyle="--", linewidth=1, alpha=0.5,
               label=f"Среднее {g['stop_rate_%'].mean():.1f}%")
    ax.legend()
    return _save(fig, out_dir, "01_stop_rate_by_hour_msk")


def chart_stop_rate_by_volume(signals: pd.DataFrame, out_dir: Path) -> Path:
    if "volume_ratio" not in signals.columns:
        return None
    edges = [0, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, np.inf]
    labels = ["<0.5", "0.5–0.8", "0.8–1.0", "1.0–1.2", "1.2–1.5", "1.5–2.0", ">2.0"]
    bucket = pd.cut(signals["volume_ratio"], bins=edges, labels=labels)
    g = signals.assign(b=bucket).groupby("b", observed=True)["result"].agg(
        total="count",
        losses=lambda x: (x == "loss").sum(),
    )
    g["stop_rate_%"] = g["losses"] / g["total"] * 100.0

    fig, ax = plt.subplots()
    ax.bar(g.index.astype(str), g["stop_rate_%"], color="#cc4444")
    ax.set_xlabel("volume_ratio (объём 3 свечей / 3× час до)")
    ax.set_ylabel("Доля проигрышей, %")
    ax.set_title("Доля проигрышей по объёму первых 3 свечей")
    for i, v in enumerate(g["total"]):
        ax.text(i, g["stop_rate_%"].iloc[i] + 0.2, f"n={v}", ha="center", fontsize=8, color="gray")
    return _save(fig, out_dir, "02_stop_rate_by_volume_bucket")


def chart_stop_rate_by_taker(signals: pd.DataFrame, out_dir: Path) -> Path:
    if "taker_with_series_ratio" not in signals.columns:
        return None
    edges = [-np.inf, 0.45, 0.50, 0.55, 0.60, 0.65, np.inf]
    labels = ["<0.45", "0.45–0.50", "0.50–0.55", "0.55–0.60", "0.60–0.65", ">0.65"]
    bucket = pd.cut(signals["taker_with_series_ratio"], bins=edges, labels=labels)
    g = signals.assign(b=bucket).groupby("b", observed=True)["result"].agg(
        total="count",
        losses=lambda x: (x == "loss").sum(),
    )
    g["stop_rate_%"] = g["losses"] / g["total"] * 100.0

    fig, ax = plt.subplots()
    ax.bar(g.index.astype(str), g["stop_rate_%"], color="#cc8844")
    ax.set_xlabel("taker imbalance в направлении серии")
    ax.set_ylabel("Доля проигрышей, %")
    ax.set_title("Доля проигрышей по taker imbalance")
    for i, v in enumerate(g["total"]):
        ax.text(i, g["stop_rate_%"].iloc[i] + 0.2, f"n={v}", ha="center", fontsize=8, color="gray")
    return _save(fig, out_dir, "03_stop_rate_by_taker_bucket")


def chart_stop_rate_breakout_vs_no(signals: pd.DataFrame, out_dir: Path) -> Path:
    if "breakout_60m_with_series" not in signals.columns:
        return None
    cats = {
        "Нет пробоя 60м": signals["breakout_60m_with_series"] != 1,
        "Есть пробой 60м": signals["breakout_60m_with_series"] == 1,
    }
    rates = []
    counts = []
    for name, mask in cats.items():
        sub = signals[mask]
        total = len(sub)
        losses = int((sub["result"] == "loss").sum())
        rates.append(losses / total * 100 if total else 0)
        counts.append(total)

    fig, ax = plt.subplots()
    bars = ax.bar(list(cats.keys()), rates, color=["#4488cc", "#cc4444"])
    ax.set_ylabel("Доля проигрышей, %")
    ax.set_title("Доля проигрышей: с пробоем 60м vs без пробоя")
    for i, (r, c) in enumerate(zip(rates, counts)):
        ax.text(i, r + 0.2, f"{r:.1f}%\n(n={c})", ha="center", fontsize=9)
    return _save(fig, out_dir, "04_stop_rate_breakout_vs_no")


def chart_pnl_by_window(signals: pd.DataFrame, out_dir: Path, hours: int, name: str) -> Path:
    if "hour_msk" not in signals.columns or "pnl" not in signals.columns:
        return None
    bins = list(range(0, 25, hours))
    labels = [f"{bins[i]:02d}–{bins[i+1]:02d}" for i in range(len(bins) - 1)]
    bucket = pd.cut(signals["hour_msk"].astype(float), bins=bins, labels=labels, right=False, include_lowest=True)
    g = signals.assign(b=bucket).groupby("b", observed=True)["pnl"].agg(
        total_pnl="sum",
        n="count",
    )
    fig, ax = plt.subplots()
    colors = ["#5cb85c" if v >= 0 else "#cc4444" for v in g["total_pnl"]]
    ax.bar(g.index.astype(str), g["total_pnl"], color=colors)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_xlabel(f"{hours}-часовое окно (МСК)")
    ax.set_ylabel("PnL")
    ax.set_title(f"PnL по {hours}-часовым окнам (МСК)")
    for i, (v, n) in enumerate(zip(g["total_pnl"], g["n"])):
        ax.text(i, v + (0.5 if v >= 0 else -0.5), f"{v:+.0f}\nn={n}",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    return _save(fig, out_dir, name)


def chart_long_series_length_distribution(series: pd.DataFrame, out_dir: Path, threshold: int = 7) -> Path:
    long_s = series[series["length"] >= threshold]
    if long_s.empty:
        return None
    counts = long_s["length"].value_counts().sort_index()

    fig, ax = plt.subplots()
    ax.bar(counts.index.astype(int), counts.values, color="#cc4444")
    ax.set_xlabel("Длина серии (свечей подряд)")
    ax.set_ylabel("Количество серий")
    ax.set_title(f"Распределение длинных серий (≥ {threshold})")
    ax.set_xticks(range(int(counts.index.min()), int(counts.index.max()) + 1))
    for x, y in zip(counts.index.astype(int), counts.values):
        ax.text(x, y + 0.5, str(int(y)), ha="center", fontsize=9)
    return _save(fig, out_dir, "07_long_series_length_distribution")


def make_all(
    signals_with_pnl: pd.DataFrame,
    series: pd.DataFrame,
    out_dir: Path,
    long_threshold: int = 7,
) -> list[Path]:
    _setup_style()
    out_dir = Path(out_dir)
    results: list[Path] = []
    for fn, name in [
        (lambda: chart_stop_rate_by_hour(signals_with_pnl, out_dir), "stop_rate_by_hour_msk"),
        (lambda: chart_stop_rate_by_volume(signals_with_pnl, out_dir), "stop_rate_by_volume_bucket"),
        (lambda: chart_stop_rate_by_taker(signals_with_pnl, out_dir), "stop_rate_by_taker_bucket"),
        (lambda: chart_stop_rate_breakout_vs_no(signals_with_pnl, out_dir), "stop_rate_breakout_vs_no"),
        (lambda: chart_pnl_by_window(signals_with_pnl, out_dir, 3, "05_pnl_by_3h_window_msk"), "pnl_by_3h_window"),
        (lambda: chart_pnl_by_window(signals_with_pnl, out_dir, 6, "06_pnl_by_6h_window_msk"), "pnl_by_6h_window"),
        (lambda: chart_long_series_length_distribution(series, out_dir, long_threshold), "long_series_distribution"),
    ]:
        try:
            p = fn()
            if p is not None:
                results.append(p)
        except Exception as e:  # noqa: BLE001
            print(f"[charts] {name} FAILED: {e}")
    return results
