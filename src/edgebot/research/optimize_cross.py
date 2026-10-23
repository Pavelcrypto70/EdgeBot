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
    "atr_mult": [1.0, 1.2, 1.5],
    "take_profit_r": [1.2, 1.5, 2.0],
    "min_htf_slope": [0.0, 0.0008],  # 0 = крест без фильтра HTF
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


def _score(all_m: dict[str, Any], oos_m: dict[str, Any]) -> float:
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
    sc = wr * 100.0 + min(exp, 1.0) * 8.0 + min(pf, 3.0) * 2.0
    if oos_n >= g.min_oos_trades:
        sc += oos_wr * 25.0 + min(oos_exp, 1.0) * 6.0
    else:
        sc -= 20.0
    if wr < g.target_winrate or exp < 0 or pf < 1.0:
        sc -= 30.0
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
        sc = _score(all_m, oos_m)
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
