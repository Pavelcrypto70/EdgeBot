from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def enrich(df: pd.DataFrame, *, ema_fast: int = 20, ema_slow: int = 50, atr_period: int = 14) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], ema_fast)
    out["ema_slow"] = ema(out["close"], ema_slow)
    out["atr"] = atr(out, atr_period)
    out["atr_pct"] = out["atr"] / out["close"]
    out["ema_slow_slope"] = out["ema_slow"].pct_change(10)
    out["rsi"] = rsi(out["close"], 14)
    out["ret_1"] = out["close"].pct_change()
    vol_ma = out["volume"].rolling(20).mean()
    out["rvol"] = out["volume"] / vol_ma.replace(0, np.nan)
    return out
