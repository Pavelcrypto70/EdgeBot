from __future__ import annotations

from dataclasses import asdict
from itertools import product
from typing import Any

import pandas as pd

from edgebot.backtest.engine import simulate_signals, split_train_oos, summarize_trades
from edgebot.strategies.ema_ma import StrategyParams, generate_signals

# Отдельная сетка под кресты на тяжёлых (медленнее / чище)
CROSS_GRID = {
    "ema_fast": [12, 15, 20, 25, 30],
    "ema_slow": [40, 50, 60, 80, 100],
    "atr_mult": [1.6, 1.8, 2.0],  # v10: шире стоп после live 77% stops
    "take_profit_r": [2.0, 2.5],
    "min_htf_slope": [0.0, 0.0008],
}


def _cross_params() -> list[StrategyParams]:
    keys = list(CROSS_GRID.keys())
    out: list[StrategyParams] = []
    for vals in product(*(CROSS_GRID[k] for k in keys)):
        kw = dict(zip(keys, vals, strict=True))
        if kw["ema_fast"] >= kw["ema_slow"]:
            continue
        if kw["ema_slow"] < kw["ema_fast"] * 1.5:
            continue
        out.append(StrategyParams(name="cross", allow_short=True, **kw))
    return out


def _score(all_m: dict[str, Any], oos_m: dict[str, Any], tp_r: float) -> float:
    from edgebot.research.proof import ProofGates

    g = ProofGates()
    n = int(all_m.get("trades", 0) or 0)
    wr = float(all_m.get("winrate", 0) or 0)
    exp = float(all_m.get("expectancy_r", 0) or 0)
    pf = float(all_m.get("profit_factor", 0) or 0)
    oos_n = int(oos_m.get("trades", 0) or 0)
    oos_wr = float(oos_m.get("winrate", 0) or 0)
    oos_exp = float(oos_m.get("expectancy_r", 0) or 0)
    if n < g.min_trades:
        return -999.0
    rr_bonus = max(0.0, tp_r - 1.5) * 10.0
    sc = wr * 40.0 + min(exp, 1.5) * 45.0 + min(pf, 4.0) * 8.0 + rr_bonus
    if oos_n >= g.min_oos_trades:
        sc += oos_wr * 15.0 + min(oos_exp, 1.5) * 20.0
    else:
        sc -= 25.0
    if wr < g.target_winrate or exp < g.min_expectancy_r or pf < g.min_profit_factor:
        sc -= 35.0
    if tp_r < g.min_take_profit_r:
        sc -= 40.0
    return sc


def optimize_cross_symbol(
    entry: pd.DataFrame,
    htf: pd.DataFrame,
    *,
    allow_short: bool = True,
    oos_frac: float = 0.3,
    fee_rate: float = 0.00055,
) -> dict[str, Any]:
    """Поиск оптимального пересечения EMA (только режим cross)."""
    cut, _ = split_train_oos(len(entry), oos_frac)
    best: dict[str, Any] | None = None

    for params in _cross_params():
        p = StrategyParams(**{**asdict(params), "allow_short": allow_short})
        sigs = generate_signals(entry, htf, p, allow_short=allow_short)
        if sigs.empty:
            continue
        trades = simulate_signals(entry, sigs, fee_rate=fee_rate)
        if trades.empty:
            continue
        all_m = summarize_trades(trades)
        train_m = summarize_trades(trades[trades["entry_i"] < cut])
        oos_m = summarize_trades(trades[trades["entry_i"] >= cut])
        sc = _score(all_m, oos_m, float(p.take_profit_r))
        cand = {
            "params": asdict(p),
            "all": all_m,
            "train": train_m,
            "oos": oos_m,
            "score": sc,
            "all_trades": trades,
            "winrate": float(all_m["winrate"]),
            "winrate_pct": round(float(all_m["winrate"]) * 100, 1),
        }
        if best is None or sc > best["score"]:
            best = cand

    if best is None:
        empty = summarize_trades(pd.DataFrame())
        return {
            "ok": False,
            "reason": "no_cross_signals",
            "params": None,
            "all": empty,
            "train": empty,
            "oos": empty,
            "score": -999.0,
            "winrate": 0.0,
            "winrate_pct": 0.0,
        }
    return {"ok": True, "reason": "cross_optimized", **best}
