from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def simulate_signals(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    fee_rate: float = 0.00055,
    slippage_bps: float = 3.0,
) -> pd.DataFrame:
    """Bar-walk exits: stop / take. PnL in R (risk units)."""
    if signals is None or signals.empty or bars.empty:
        return pd.DataFrame()

    slip = slippage_bps / 10_000
    trades: list[dict[str, Any]] = []
    busy_until = -1

    for sig in signals.itertuples(index=False):
        start = int(sig.i) + 1
        if start <= busy_until or start >= len(bars):
            continue
        side = sig.side
        entry = float(sig.entry) * (1 + slip if side == "long" else 1 - slip)
        stop = float(sig.stop)
        take = float(sig.take)
        risk = abs(entry - stop)
        if risk <= 0:
            continue

        exit_price = None
        exit_i = None
        reason = "timeout"
        for j in range(start, len(bars)):
            hi = float(bars["high"].iloc[j])
            lo = float(bars["low"].iloc[j])
            if side == "long":
                hit_stop = lo <= stop
                hit_take = hi >= take
                if hit_stop and hit_take:
                    exit_price, reason = stop, "stop"
                elif hit_stop:
                    exit_price, reason = stop, "stop"
                elif hit_take:
                    exit_price, reason = take, "take"
            else:
                hit_stop = hi >= stop
                hit_take = lo <= take
                if hit_stop and hit_take:
                    exit_price, reason = stop, "stop"
                elif hit_stop:
                    exit_price, reason = stop, "stop"
                elif hit_take:
                    exit_price, reason = take, "take"
            if exit_price is not None:
                exit_i = j
                break
        if exit_price is None:
            exit_i = len(bars) - 1
            exit_price = float(bars["close"].iloc[exit_i])
            reason = "eod"

        exit_price = exit_price * (1 - slip if side == "long" else 1 + slip)
        raw = (exit_price - entry) / risk if side == "long" else (entry - exit_price) / risk
        fees_r = (2 * fee_rate * entry) / risk
        pnl_r = raw - fees_r
        busy_until = exit_i
        trades.append(
            {
                "entry_i": int(sig.i),
                "exit_i": exit_i,
                "side": side,
                "entry": entry,
                "exit": exit_price,
                "pnl_r": pnl_r,
                "win": pnl_r > 0,
                "reason": reason,
                "ts": getattr(sig, "ts", None),
            }
        )
    return pd.DataFrame(trades)


def summarize_trades(trades: pd.DataFrame) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {
            "trades": 0,
            "winrate": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "net_r": 0.0,
        }
    wins = trades.loc[trades["pnl_r"] > 0, "pnl_r"]
    losses = trades.loc[trades["pnl_r"] <= 0, "pnl_r"]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float((-losses).sum()) if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    return {
        "trades": int(len(trades)),
        "winrate": float(trades["win"].mean()),
        "expectancy_r": float(trades["pnl_r"].mean()),
        "profit_factor": float(pf),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "net_r": float(trades["pnl_r"].sum()),
    }


def split_train_oos(n: int, oos_frac: float = 0.3) -> tuple[int, int]:
    cut = int(n * (1.0 - oos_frac))
    return max(cut, 50), n
