"""Бэктест стратегии «мартингейл против серии» + набор фильтров.

Базовая стратегия:
  - После 3 одинаковых исходов подряд (UP/DOWN) — ставим против.
  - До `max_attempts` догонов (по дефолту 3).
  - Ставки удваиваются: base_stake * 2^i (по дефолту 1, 2, 4).
  - Выплата `payout` (по дефолту 1.8 — типично для Polymarket BTC 5m).
  - Чистая прибыль при выигрыше на шаге N: stake_N * (payout - 1) − сумма
    предыдущих ставок. При проигрыше: − сумма всех ставок.

Фильтры — это правила пропуска сигнала. На входе DataFrame сигналов
с признаками (см. analysis/features.py). На выходе булева маска
«пропустить или нет». Применённый фильтр уменьшает число сигналов и
меняет статистику.

Два набора фильтров:
  - tz_*  — 5 фильтров из ТЗ заказчика (гипотеза: длинные серии = пробой +
            объём + имбаланс). По нашим данным эта гипотеза не подтверждается.
  - inv_* — 5 «инвертированных» фильтров (длинные серии = тихий рынок).
            Соответствует тому, что показал анализ wins vs long-losses.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestConfig:
    payout: float = 1.8
    base_stake: float = 1.0
    max_attempts: int = 3
    stake_mode: str = "doubling"  # "doubling" | "fixed"


def _stakes(cfg: BacktestConfig) -> list[float]:
    if cfg.stake_mode == "doubling":
        return [cfg.base_stake * (2 ** i) for i in range(cfg.max_attempts)]
    return [cfg.base_stake] * cfg.max_attempts


def recompute_outcome(signals: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Reset `result` / `win_attempt` for the current cfg.max_attempts.

    Lets us re-run backtest with different max_attempts without re-running
    the whole analyze pipeline.
    """
    s = signals.copy()
    length = s["final_series_length"]
    cutoff = 3 + cfg.max_attempts          # series length at which we lose
    s["result"] = np.where(length < cutoff, "win", "loss")
    s["win_attempt"] = np.where(length < cutoff, length - 2, np.nan)
    return s


def compute_pnl(signals: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Add `pnl` column (net profit/loss per signal in currency units)."""
    stakes = _stakes(cfg)
    cumloss = sum(stakes)                  # loss when all attempts fail

    def row_pnl(r):
        if r["result"] == "loss":
            return -cumloss
        a = int(r["win_attempt"]) - 1      # 0-indexed
        prior = sum(stakes[:a])
        return stakes[a] * (cfg.payout - 1) - prior

    out = signals.copy()
    out["pnl"] = out.apply(row_pnl, axis=1)
    return out


# ---------- Фильтры ----------
# Each function returns a boolean Series: True means SKIP this signal.

def f_tz1_breakout_60m(s):
    return s["breakout_60m_with_series"] == 1


def f_tz2_volume(s, threshold=1.5):
    return s["volume_ratio"] > threshold


def f_tz3_taker(s, threshold=0.60):
    return s["taker_with_series_ratio"] > threshold


def f_tz4_body_extreme(s, body_thr=0.6):
    body = s["body_to_range_3rd"] > body_thr
    cp_up = (s["direction"] == "UP") & (s["close_position_3rd"] > 0.75)
    cp_dn = (s["direction"] == "DOWN") & (s["close_position_3rd"] < 0.25)
    return body & (cp_up | cp_dn)


def f_tz5_combo(s):
    c1 = (s["breakout_60m_with_series"] == 1).fillna(False)
    c2 = (s["volume_ratio"] > 1.5).fillna(False)
    c3 = (s["taker_with_series_ratio"] > 0.60).fillna(False)
    c4 = f_tz4_body_extreme(s).fillna(False)
    return (c1.astype(int) + c2.astype(int) + c3.astype(int) + c4.astype(int)) >= 2


def f_inv1_no_breakout(s):
    no60 = (s["breakout_60m_with_series"] != 1).fillna(True)
    no3h = (s["breakout_3h_with_series"] != 1).fillna(True)
    return no60 & no3h


def f_inv2_low_volume(s, threshold=0.8):
    return s["volume_ratio"] < threshold


def f_inv3_balanced_taker(s, eps=0.05):
    return (s["taker_with_series_ratio"] - 0.5).abs() < eps


def f_inv4_doji(s, body_thr=0.3):
    return s["body_to_range_3bar_avg"] < body_thr


def f_inv5_combo(s):
    c1 = f_inv1_no_breakout(s).fillna(False)
    c2 = f_inv2_low_volume(s).fillna(False)
    c3 = f_inv3_balanced_taker(s).fillna(False)
    c4 = f_inv4_doji(s).fillna(False)
    return (c1.astype(int) + c2.astype(int) + c3.astype(int) + c4.astype(int)) >= 2


# (key, имя_для_отчёта, описание_на_русском, функция_пропуска)
FILTERS = [
    ("baseline",         "Без фильтров",                "Все сигналы; ничего не пропускаем (база для сравнения).",                       lambda s: pd.Series(False, index=s.index)),
    ("tz_1_breakout60",  "ТЗ-1: пробой 60м",            "Пропуск если 3-я свеча пробила hi/lo последних 60м в направлении серии.",       f_tz1_breakout_60m),
    ("tz_2_volume",      "ТЗ-2: объём > 1.5x",          "Пропуск если объём 3 свечей > 1.5x от среднего за час до.",                     f_tz2_volume),
    ("tz_3_taker",       "ТЗ-3: taker > 0.60",          "Пропуск если taker imbalance > 60% в сторону серии (агрессия в ту же сторону).",f_tz3_taker),
    ("tz_4_body",        "ТЗ-4: импульсная свеча",      "Пропуск если 3-я свеча плотная (body/range>0.6) и закрылась у экстремума.",     f_tz4_body_extreme),
    ("tz_5_combo",       "ТЗ-5: ≥2 из 4 (ТЗ)",          "Пропуск если выполнены ≥2 из 4 условий ТЗ.",                                    f_tz5_combo),
    ("inv_1_no_breakout","Инверт-1: нет пробоя",        "Пропуск если НЕТ ни одного пробоя в 60м и в 3ч (тихий рынок).",                 f_inv1_no_breakout),
    ("inv_2_low_volume", "Инверт-2: тихий объём",       "Пропуск если объём 3 свечей < 0.8x от среднего за час до.",                     f_inv2_low_volume),
    ("inv_3_balanced",   "Инверт-3: баланс taker",      "Пропуск если taker близок к 50/50 (±5%) — нет агрессии ни в одну сторону.",     f_inv3_balanced_taker),
    ("inv_4_doji",       "Инверт-4: доджи",             "Пропуск если средний body/range у 3 свечей < 0.3 (свечи без направления).",     f_inv4_doji),
    ("inv_5_combo",      "Инверт-5: ≥2 из 4 (тихий)",   "Пропуск если выполнены ≥2 из 4 условий 'тихого рынка'.",                        f_inv5_combo),
]


def _summary_row(name_key, ru_name, desc, period, signals_kept, n_total) -> dict:
    n_kept = len(signals_kept)
    skipped = n_total - n_kept
    wins = int((signals_kept["result"] == "win").sum())
    losses = int((signals_kept["result"] == "loss").sum())
    win_rate = wins / n_kept if n_kept else 0.0
    pnl = float(signals_kept["pnl"].sum()) if "pnl" in signals_kept.columns and n_kept else 0.0
    avg_pnl = pnl / n_kept if n_kept else 0.0

    max_dd = 0.0
    if n_kept > 0 and "pnl" in signals_kept.columns:
        eq = signals_kept.sort_values("signal_open_time")["pnl"].cumsum()
        peak = eq.cummax()
        max_dd = float((eq - peak).min())

    return {
        "стратегия_код": name_key,
        "стратегия": ru_name,
        "описание": desc,
        "период": period,
        "сигналов_всего": int(n_total),
        "пропущено": int(skipped),
        "осталось": n_kept,
        "побед": wins,
        "проигрышей": losses,
        "win_rate_%": round(win_rate * 100, 2),
        "PnL_всего": round(pnl, 2),
        "PnL_на_сигнал": round(avg_pnl, 3),
        "max_drawdown": round(max_dd, 2),
    }


def run_full_backtest(
    signals: pd.DataFrame,
    cfg: BacktestConfig,
    train_end: str = "2026-03-31T23:59:59Z",
) -> pd.DataFrame:
    """Apply each filter to the full dataset and to train/test halves.

    Returns a flat DataFrame with one row per (filter, period).
    """
    s = recompute_outcome(signals, cfg)
    s = compute_pnl(s, cfg)
    s["signal_open_time"] = pd.to_datetime(s["signal_open_time"], utc=True)

    train_end_ts = pd.Timestamp(train_end)
    train = s[s["signal_open_time"] <= train_end_ts]
    test = s[s["signal_open_time"] > train_end_ts]

    rows: list[dict] = []
    for key, ru_name, desc, fn in FILTERS:
        for period_name, subset in (("весь_период", s), ("train", train), ("test", test)):
            mask_skip = fn(subset).fillna(False)
            kept = subset[~mask_skip]
            rows.append(_summary_row(key, ru_name, desc, period_name, kept, len(subset)))

    return pd.DataFrame(rows)
