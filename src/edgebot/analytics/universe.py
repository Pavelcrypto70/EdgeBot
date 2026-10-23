from __future__ import annotations

from typing import Any

import pandas as pd

from edgebot.bybit.client import BybitClient
from edgebot.bybit.demo_data import demo_universe
from edgebot.config import AppConfig, get_settings, load_config


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _spread_bps(bid: float, ask: float) -> float | None:
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return (ask - bid) / mid * 10_000


def tickers_to_frame(raw: list[dict[str, Any]], category: str, quote: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in raw:
        symbol = str(item.get("symbol") or "")
        if not symbol.endswith(quote):
            continue
        bid = _f(item.get("bid1Price"))
        ask = _f(item.get("ask1Price"))
        rows.append(
            {
                "symbol": symbol,
                "category": category,
                "last_price": _f(item.get("lastPrice")),
                "turnover_24h": _f(item.get("turnover24h")),
                "volume_24h": _f(item.get("volume24h")),
                "price_change_pct_24h": _f(item.get("price24hPcnt")) * 100,
                "spread_bps": _spread_bps(bid, ask),
                "open_interest": _f(item.get("openInterest")),
                "funding_rate": _f(item.get("fundingRate")) if category == "linear" else None,
                "demo": False,
            }
        )
    return pd.DataFrame(rows)


def screen_tickers(client: BybitClient, cfg: AppConfig | None = None) -> pd.DataFrame:
    """Hard liquidity/spread prefilter across categories."""
    cfg = cfg or load_config()
    settings = get_settings()
    if settings.edgebot_demo == "always":
        return demo_universe(cfg.universe.top_n_raw)

    frames: list[pd.DataFrame] = []
    try:
        for category in cfg.universe.categories:
            frame = tickers_to_frame(
                client.tickers(category),
                category,
                cfg.universe.quote.upper(),
            )
            if not frame.empty:
                frames.append(frame)
        if not frames:
            raise RuntimeError("empty ticker universe")
        universe = pd.concat(frames, ignore_index=True)
    except Exception:
        if settings.edgebot_demo == "never":
            raise
        return demo_universe(cfg.universe.top_n_raw)

    blacklist = {s.upper() for s in cfg.universe.blacklist}
    universe = universe[~universe["symbol"].str.upper().isin(blacklist)].copy()
    universe = universe[universe["turnover_24h"] >= cfg.universe.min_turnover_usdt]
    universe = universe[
        universe["spread_bps"].isna() | (universe["spread_bps"] <= cfg.universe.max_spread_bps)
    ]

    if cfg.universe.prefer_linear:
        universe["_rank_cat"] = universe["category"].map({"linear": 0, "spot": 1}).fillna(2)
        universe = universe.sort_values(
            ["_rank_cat", "turnover_24h"],
            ascending=[True, False],
        ).drop(columns=["_rank_cat"])
    else:
        universe = universe.sort_values("turnover_24h", ascending=False)

    # Keep best row per symbol (prefer linear if both exist)
    universe = universe.drop_duplicates(subset=["symbol"], keep="first")
    return universe.head(cfg.universe.top_n_raw).reset_index(drop=True)
