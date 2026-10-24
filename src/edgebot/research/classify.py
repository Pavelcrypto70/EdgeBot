from __future__ import annotations

import pandas as pd

# Медленные / majors
TIER1 = {
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "NEARUSDT",
    "ATOMUSDT",
    "UNIUSDT",
    "AAVEUSDT",
    "TRXUSDT",
    "TONUSDT",
    "SUIUSDT",
    "APTUSDT",
}


def classify_universe(
    universe: pd.DataFrame,
    *,
    heavy_top_n: int = 12,
    medium_top_n: int = 8,
    fast_min_abs_delta_pct: float = 3.5,
    fast_top_n: int = 6,
) -> pd.DataFrame:
    """
    Три режима:
    - heavy (медленные): tier-1 + топ оборота
    - medium (средние): следующий эшелон по обороту
    - fast (быстрые): крупная |Δ 24h| среди остальных
    """
    if universe is None or universe.empty:
        return universe

    df = universe.copy()
    df["abs_delta"] = df["price_change_pct_24h"].abs()
    df = df.sort_values("turnover_24h", ascending=False).reset_index(drop=True)

    in_universe = set(df["symbol"].astype(str))
    heavy_syms = (TIER1 & in_universe) | set(df.head(heavy_top_n)["symbol"].astype(str))

    rest = df[~df["symbol"].astype(str).isin(heavy_syms)].copy()
    medium_syms = set(rest.head(medium_top_n)["symbol"].astype(str))

    fast_pool = rest[~rest["symbol"].astype(str).isin(medium_syms)].copy()
    fast_pool = fast_pool[fast_pool["abs_delta"] >= float(fast_min_abs_delta_pct)]
    fast_pool = fast_pool.sort_values("abs_delta", ascending=False).head(fast_top_n)
    fast_syms = set(fast_pool["symbol"].astype(str))

    def _bucket(sym: str) -> str:
        if sym in heavy_syms:
            return "heavy"
        if sym in medium_syms:
            return "medium"
        if sym in fast_syms:
            return "fast"
        return "skip"

    df["bucket"] = df["symbol"].astype(str).map(_bucket)
    out = df[df["bucket"] != "skip"].copy()
    return out.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
