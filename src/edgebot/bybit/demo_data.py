from __future__ import annotations

import numpy as np
import pandas as pd


def demo_universe(n: int = 40) -> pd.DataFrame:
    """Synthetic liquid universe when Bybit is unreachable."""
    rng = np.random.default_rng(42)
    symbols = [f"COIN{i:02d}USDT" for i in range(1, n + 1)]
    cats = ["linear" if i % 3 else "spot" for i in range(1, n + 1)]
    turnovers = rng.uniform(3e6, 2e8, size=n)
    prices = rng.uniform(0.1, 80_000, size=n)
    spreads = rng.uniform(1.0, 10.0, size=n)
    chg = rng.normal(0, 4, size=n)
    return pd.DataFrame(
        {
            "symbol": symbols,
            "category": cats,
            "last_price": prices,
            "turnover_24h": turnovers,
            "volume_24h": turnovers / np.maximum(prices, 1e-9),
            "price_change_pct_24h": chg,
            "spread_bps": spreads,
            "open_interest": rng.uniform(1e5, 5e7, size=n),
            "funding_rate": rng.normal(0, 0.0003, size=n),
            "demo": True,
        }
    )


def demo_klines(bars: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0002, 0.004, size=bars)
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.008, size=bars))
    low = close * (1 - rng.uniform(0.001, 0.008, size=bars))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    vol = rng.uniform(50, 500, size=bars)
    ts = pd.date_range(end=pd.Timestamp.utcnow(), periods=bars, freq="15min")
    return pd.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )
