from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from edgebot.analytics.indicators import enrich


@dataclass(frozen=True, slots=True)
class StrategyParams:
    name: str  # heavy | medium | fast | cross
    ema_fast: int
    ema_slow: int
    atr_mult: float
    take_profit_r: float
    min_htf_slope: float = 0.0
    allow_short: bool = True


HEAVY_DEFAULT = StrategyParams(
    name="heavy",
    ema_fast=20,
    ema_slow=60,
    atr_mult=1.8,
    take_profit_r=2.5,
    min_htf_slope=0.0005,
    allow_short=True,
)

MEDIUM_DEFAULT = StrategyParams(
    name="medium",
    ema_fast=15,
    ema_slow=50,
    atr_mult=1.7,
    take_profit_r=2.0,
    min_htf_slope=0.0003,
    allow_short=True,
)

FAST_DEFAULT = StrategyParams(
    name="fast",
    ema_fast=9,
    ema_slow=26,
    atr_mult=1.6,
    take_profit_r=2.0,
    min_htf_slope=0.0005,
    allow_short=True,
)


def generate_signals(
    entry: pd.DataFrame,
    htf: pd.DataFrame,
    params: StrategyParams,
    *,
    allow_short: bool | None = None,
) -> pd.DataFrame:
    """
    Три режима:
    - heavy: медленный крест + жёсткий HTF + цена vs HTF EMA
    - medium: средний крест + мягкий HTF
    - fast: короткий крест + HTF (без pullback-спама)
    - cross: чистый крест (для heavy research)
    """
    short_ok = params.allow_short if allow_short is None else allow_short
    e = enrich(entry, ema_fast=params.ema_fast, ema_slow=params.ema_slow)
    h = enrich(htf, ema_fast=params.ema_fast, ema_slow=params.ema_slow)
    if e.empty or h.empty:
        return pd.DataFrame()

    if "ts" in e.columns and "ts" in h.columns:
        left = e.reset_index(drop=True)
        right = h[["ts", "ema_slow_slope", "ema_slow"]].rename(
            columns={"ema_slow_slope": "htf_slope", "ema_slow": "htf_ema"}
        )
        left = left.sort_values("ts")
        right = right.sort_values("ts")
        e = pd.merge_asof(left, right, on="ts", direction="backward")
    else:
        e = e.copy()
        e["htf_slope"] = (
            float(h["ema_slow_slope"].dropna().iloc[-1]) if h["ema_slow_slope"].notna().any() else 0.0
        )
        e["htf_ema"] = float(h["ema_slow"].iloc[-1])

    e["prev_fast"] = e["ema_fast"].shift(1)
    e["prev_slow"] = e["ema_slow"].shift(1)
    cross_up = (e["prev_fast"] <= e["prev_slow"]) & (e["ema_fast"] > e["ema_slow"])
    cross_dn = (e["prev_fast"] >= e["prev_slow"]) & (e["ema_fast"] < e["ema_slow"])
    slope = float(params.min_htf_slope or 0.0)

    if params.name == "fast":
        # Без pullback: только крест + направление HTF (иначе ночной спам)
        long_sig = cross_up & (e["htf_slope"] > slope)
        short_sig = cross_dn & (e["htf_slope"] < -slope)
    elif params.name == "medium":
        if slope <= 0:
            long_sig = cross_up
            short_sig = cross_dn
        else:
            long_sig = cross_up & (e["htf_slope"] >= 0)
            short_sig = cross_dn & (e["htf_slope"] <= 0)
    elif params.name == "cross":
        if slope <= 0:
            long_sig = cross_up
            short_sig = cross_dn
        else:
            long_sig = cross_up & (e["htf_slope"] >= 0)
            short_sig = cross_dn & (e["htf_slope"] <= 0)
    else:
        # heavy / slow
        long_sig = cross_up & (e["htf_slope"] > slope) & (e["close"] >= e["htf_ema"])
        short_sig = cross_dn & (e["htf_slope"] < -slope) & (e["close"] <= e["htf_ema"])

    rows: list[dict] = []
    for i in range(len(e)):
        side = None
        if bool(long_sig.iloc[i]):
            side = "long"
        elif short_ok and bool(short_sig.iloc[i]):
            side = "short"
        if side is None:
            continue
        atr_v = float(e["atr"].iloc[i])
        if not atr_v or atr_v != atr_v:
            continue
        price = float(e["close"].iloc[i])
        risk = params.atr_mult * atr_v
        if side == "long":
            stop = price - risk
            take = price + params.take_profit_r * risk
        else:
            stop = price + risk
            take = price - params.take_profit_r * risk
        rows.append(
            {
                "i": i,
                "ts": e["ts"].iloc[i] if "ts" in e.columns else i,
                "side": side,
                "entry": price,
                "stop": stop,
                "take": take,
                "atr": atr_v,
                "risk": risk,
            }
        )
    return pd.DataFrame(rows)
