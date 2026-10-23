from __future__ import annotations

from dataclasses import asdict
from itertools import product
from typing import Any

import pandas as pd

from edgebot.backtest.engine import simulate_signals, split_train_oos, summarize_trades
from edgebot.strategies.ema_ma import StrategyParams, generate_signals

# Тяжёлые — спокойнее
HEAVY_GRID = {
    "ema_fast": [12, 15, 20, 25],
    "ema_slow": [34, 50, 80, 100],
    "atr_mult": [1.0, 1.2, 1.5],
    "take_profit_r": [1.0, 1.5, 2.0],
    "min_htf_slope": [0.0, 0.0005],
}

# Быстрые монеты — короткие EMA, чаще входы
FAST_GRID = {
    "ema_fast": [5, 8, 9, 12],
    "ema_slow": [13, 21, 26, 34],
    "atr_mult": [0.9, 1.0, 1.2],
    "take_profit_r": [1.0, 1.2, 1.5],
    "min_htf_slope": [0.0, 0.0003],
}


def _param_grid(bucket: str = "heavy") -> list[StrategyParams]:
    if bucket == "fast":
        grid = FAST_GRID
        styles = ("fast", "cross")
    else:
        grid = HEAVY_GRID
        styles = ("heavy", "cross")
    keys = list(grid.keys())
    out: list[StrategyParams] = []
    for style in styles:
        for vals in product(*(grid[k] for k in keys)):
            kw = dict(zip(keys, vals, strict=True))
            if kw["ema_fast"] >= kw["ema_slow"]:
                continue
            if kw["ema_slow"] / max(kw["ema_fast"], 1) > 8:
                continue
            out.append(StrategyParams(name=style, allow_short=True, **kw))
    return out


def _score(metrics: dict[str, Any]) -> float:
    """Главное — винрейт при достаточном числе сделок."""
    n = int(metrics.get("trades", 0) or 0)
    wr = float(metrics.get("winrate", 0) or 0)
    exp = float(metrics.get("expectancy_r", 0) or 0)
    if n < 8:
        return -999.0
    # winrate в приоритете; чуть бонуса за плюсовое мат.ожидание и объём сделок
    return wr * 100.0 + min(exp, 1.0) * 4.0 + min(n, 50) * 0.04


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
        sc = _score(all_m)
        # если OOS тоже нормальный — чуть подтягиваем
        if oos_m["trades"] >= 5:
            sc += float(oos_m["winrate"]) * 8.0
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
