from __future__ import annotations

import pandas as pd

# Proxy for "heavy / top cap" when market-cap API is unavailable
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
    heavy_top_n: int = 15,
    fast_min_abs_delta_pct: float = 4.0,
    fast_top_n: int = 20,
) -> pd.DataFrame:
    """
    Split into:
    - heavy: tier-1 majors OR top turnover names
    - fast: remaining names with large |24h delta|
    """
    if universe is None or universe.empty:
        return universe

    df = universe.copy()
    df["abs_delta"] = df["price_change_pct_24h"].abs()
    df = df.sort_values("turnover_24h", ascending=False).reset_index(drop=True)
    top_turn = set(df.head(heavy_top_n)["symbol"].tolist())

    buckets: list[str] = []
    for row in df.itertuples(index=False):
        sym = str(row.symbol)
        if sym in TIER1 or sym in top_turn:
            buckets.append("heavy")
        else:
            buckets.append("fast")
    df["bucket"] = buckets

    heavy = df[df["bucket"] == "heavy"].copy()
    fast = df[df["bucket"] == "fast"].copy()
    fast = fast[fast["abs_delta"] >= fast_min_abs_delta_pct]
    fast = fast.sort_values("abs_delta", ascending=False).head(fast_top_n)

    # Prefer linear for both
    out = pd.concat([heavy, fast], ignore_index=True)
    out = out.drop_duplicates(subset=["symbol"], keep="first")
    return out
