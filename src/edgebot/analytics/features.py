from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from edgebot.analytics.indicators import enrich
from edgebot.bybit.client import BybitClient
from edgebot.bybit.demo_data import demo_klines
from edgebot.config import AnalyticsConfig, get_settings


def klines_to_df(rows: list[list[str]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows,
        columns=["start", "open", "high", "low", "close", "volume", "turnover"],
    )
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["ts"] = pd.to_datetime(pd.to_numeric(frame["start"], errors="coerce"), unit="ms", utc=True)
    return frame.dropna(subset=["close"]).reset_index(drop=True)


def _tag_demo(frame: pd.DataFrame, *, demo: bool) -> pd.DataFrame:
    frame.attrs["edgebot_demo"] = bool(demo)
    return frame


def fetch_bars(
    client: BybitClient,
    category: str,
    symbol: str,
    interval: int,
    limit: int,
    *,
    demo_seed: int = 0,
) -> pd.DataFrame:
    settings = get_settings()
    if settings.edgebot_demo == "always":
        return _tag_demo(demo_klines(limit, seed=demo_seed), demo=True)
    try:
        rows = client.klines(category, symbol, interval, limit=limit)
        frame = klines_to_df(rows)
        if frame.empty:
            raise RuntimeError("empty klines")
        return _tag_demo(frame, demo=False)
    except Exception:
        if settings.edgebot_demo == "never":
            raise
        return _tag_demo(demo_klines(limit, seed=demo_seed), demo=True)


@dataclass(slots=True)
class SymbolFeatures:
    symbol: str
    category: str
    atr_pct: float
    htf_slope: float
    rsi: float
    ret_24h: float
    ret_7d: float
    rvol: float
    trend_aligned: bool
    structure_score: float
    realized_vol: float


def _structure_score(df: pd.DataFrame, lookback: int = 40) -> float:
    """Higher-highs / higher-lows style score in [-1, 1]."""
    if len(df) < lookback + 5:
        return 0.0
    window = df.tail(lookback)
    half = lookback // 2
    first, second = window.iloc[:half], window.iloc[half:]
    hh = float(second["high"].max() > first["high"].max())
    hl = float(second["low"].min() > first["low"].min())
    lh = float(second["high"].max() < first["high"].max())
    ll = float(second["low"].min() < first["low"].min())
    bull = (hh + hl) / 2
    bear = (lh + ll) / 2
    return bull - bear


def extract_features(entry: pd.DataFrame, htf: pd.DataFrame) -> dict[str, float]:
    e = enrich(entry)
    h = enrich(htf)
    if e.empty or h.empty:
        return {}

    atr_pct = float(e["atr_pct"].tail(50).mean())
    htf_slope = float(h["ema_slow_slope"].dropna().tail(20).mean() or 0.0)
    rsi_v = float(e["rsi"].iloc[-1]) if not np.isnan(e["rsi"].iloc[-1]) else 50.0
    # ~1 day on 15m = 96 bars; ~7d = 672 but we may have fewer
    ret_24h = float(e["close"].iloc[-1] / e["close"].iloc[max(0, len(e) - 96)] - 1) * 100
    look_7d = min(len(e) - 1, 672)
    ret_7d = float(e["close"].iloc[-1] / e["close"].iloc[-look_7d] - 1) * 100
    rvol = float(e["rvol"].tail(5).mean() or 0.0)
    trend_aligned = bool(
        (htf_slope > 0 and e["ema_fast"].iloc[-1] >= e["ema_slow"].iloc[-1])
        or (htf_slope < 0 and e["ema_fast"].iloc[-1] <= e["ema_slow"].iloc[-1])
    )
    structure = _structure_score(e)
    realized = float(e["ret_1"].tail(96).std() or 0.0) * np.sqrt(96) * 100

    return {
        "atr_pct": atr_pct,
        "htf_slope": htf_slope,
        "rsi": rsi_v,
        "ret_24h": ret_24h,
        "ret_7d": ret_7d,
        "rvol": rvol,
        "trend_aligned": float(trend_aligned),
        "structure_score": structure,
        "realized_vol": realized,
        "benchmark_ret_24h": ret_24h,  # overwritten later vs BTC
    }


def load_symbol_bundle(
    client: BybitClient,
    row: pd.Series,
    cfg: AnalyticsConfig,
    index: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    entry = fetch_bars(
        client,
        row["category"],
        row["symbol"],
        cfg.entry_tf,
        cfg.bars_entry,
        demo_seed=index + 1,
    )
    htf = fetch_bars(
        client,
        row["category"],
        row["symbol"],
        cfg.htf,
        cfg.bars_htf,
        demo_seed=index + 101,
    )
    feats = extract_features(entry, htf)
    return entry, htf, feats
