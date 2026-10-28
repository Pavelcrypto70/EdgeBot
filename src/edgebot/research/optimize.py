from __future__ import annotations

from dataclasses import asdict
from itertools import product
from typing import Any

import pandas as pd

from edgebot.backtest.engine import simulate_signals, split_train_oos, summarize_trades
from edgebot.research.proof import ProofGates
from edgebot.strategies.ema_ma import StrategyParams, generate_signals

# v10 по live: 77% стопов → шире ATR, тейк только ≥2R, без ультракоротких стопов
HEAVY_GRID = {
    "ema_fast": [15, 20, 25, 30],
    "ema_slow": [50, 60, 80, 100],
    "atr_mult": [1.6, 1.8, 2.0],
    "take_profit_r": [2.0, 2.5],
    "min_htf_slope": [0.0003, 0.0005, 0.0008],
}

MEDIUM_GRID = {
    "ema_fast": [10, 12, 15, 20],
    "ema_slow": [34, 50, 60],
    "atr_mult": [1.5, 1.7, 1.9],
    "take_profit_r": [2.0, 2.5],
    "min_htf_slope": [0.0, 0.0003, 0.0005],
}

FAST_GRID = {
    "ema_fast": [8, 9, 12],
    "ema_slow": [26, 34],
    "atr_mult": [1.4, 1.6, 1.8],
    "take_profit_r": [2.0, 2.5],
    "min_htf_slope": [0.0003, 0.0005],
}


def _param_grid(bucket: str = "heavy") -> list[StrategyParams]:
    b = (bucket or "heavy").lower()
    if b == "fast":
        grid = FAST_GRID
        styles = ("fast",)
        min_gap = 12
    elif b == "medium":
        grid = MEDIUM_GRID
        styles = ("medium", "cross")
        min_gap = 12
    else:
        grid = HEAVY_GRID
        styles = ("heavy", "cross")
        min_gap = 20
    keys = list(grid.keys())
    out: list[StrategyParams] = []
    for style in styles:
        for vals in product(*(grid[k] for k in keys)):
            kw = dict(zip(keys, vals, strict=True))
            if kw["ema_fast"] >= kw["ema_slow"]:
                continue
            if kw["ema_slow"] - kw["ema_fast"] < min_gap:
                continue
            if kw["ema_slow"] / max(kw["ema_fast"], 1) > 10:
                continue
            out.append(StrategyParams(name=style, allow_short=True, **kw))
    return out


def _score(all_m: dict[str, Any], oos_m: dict[str, Any], gates: ProofGates, tp_r: float) -> float:
    n = int(all_m.get("trades", 0) or 0)
    wr = float(all_m.get("winrate", 0) or 0)
    exp = float(all_m.get("expectancy_r", 0) or 0)
    pf = float(all_m.get("profit_factor", 0) or 0)
    oos_n = int(oos_m.get("trades", 0) or 0)
    oos_wr = float(oos_m.get("winrate", 0) or 0)
    oos_exp = float(oos_m.get("expectancy_r", 0) or 0)
    if n < gates.min_trades:
        return -999.0
    rr_bonus = max(0.0, tp_r - 1.8) * 12.0
    sc = (
        wr * 45.0
        + min(exp, 1.5) * 50.0
        + min(pf, 4.0) * 10.0
        + rr_bonus
        + min(n, 40) * 0.05
    )
    if oos_n >= gates.min_oos_trades:
        sc += oos_wr * 18.0 + min(oos_exp, 1.5) * 22.0
        if oos_exp >= gates.oos_min_expectancy_r and oos_wr >= gates.oos_target_winrate:
            sc += 10.0
        if oos_exp < 0:
            sc -= 25.0
    else:
        sc -= 25.0
    if wr < gates.target_winrate or exp < gates.min_expectancy_r or pf < gates.min_profit_factor:
        sc -= 35.0
    if tp_r < gates.min_take_profit_r:
        sc -= 40.0
    return sc


def optimize_symbol(
    entry: pd.DataFrame,
    htf: pd.DataFrame,
    bucket: str,
    *,
    allow_short: bool = True,
    oos_frac: float = 0.3,
    fee_rate: float = 0.00055,
) -> dict[str, Any]:
    cut, _n = split_train_oos(len(entry), oos_frac)
    gates = ProofGates()
    best: dict[str, Any] | None = None

    for params in _param_grid(bucket):
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
        tp_r = float(p.take_profit_r)
        sc = _score(all_m, oos_m, gates, tp_r)
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
            "reason": "no_signals",
            "params": None,
            "all": empty,
            "train": empty,
            "oos": empty,
            "score": -999.0,
            "winrate": 0.0,
            "winrate_pct": 0.0,
        }
    return {"ok": True, "reason": "optimized", **best}
