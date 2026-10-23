from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from edgebot.analytics.features import fetch_bars, load_symbol_bundle
from edgebot.analytics.score import score_row
from edgebot.analytics.universe import screen_tickers
from edgebot.bybit.client import BybitClient
from edgebot.config import AppConfig, data_dir, load_config

console = Console()


@dataclass
class AnalyticsBundle:
    universe: pd.DataFrame
    ranked: pd.DataFrame
    shortlist: pd.DataFrame
    run_dir: Path


def _btc_benchmark(client: BybitClient, cfg: AppConfig) -> float:
    a = cfg.analytics
    bars = fetch_bars(
        client,
        a.benchmark_category,
        a.benchmark_symbol,
        a.entry_tf,
        a.bars_entry,
        demo_seed=999,
    )
    if bars.empty or len(bars) < 10:
        return 0.0
    look = min(len(bars) - 1, 96)
    return float(bars["close"].iloc[-1] / bars["close"].iloc[-look] - 1) * 100


def run_analytics(
    *,
    top: int | None = None,
    cfg: AppConfig | None = None,
    quiet: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> AnalyticsBundle:
    cfg = cfg or load_config()
    if top is not None:
        cfg.analytics.shortlist_n = top

    run_dir = data_dir() / "runs" / pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if not quiet:
            console.print(msg)
        if on_progress:
            on_progress(msg)

    with BybitClient() as client:
        universe = screen_tickers(client, cfg)
        _log(f"Universe prefilter: {len(universe)} markets")
        if cfg.output.save_csv:
            universe.to_csv(run_dir / "universe_raw.csv", index=False)

        deep_n = min(cfg.analytics.deep_scan_n, len(universe))
        deep = universe.head(deep_n).copy()
        btc_ret = _btc_benchmark(client, cfg)
        _log(f"BTC 24h ref: {btc_ret:+.2f}% | deep-scan: {deep_n}")

        rows: list[dict] = []
        for i, (_, row) in enumerate(deep.iterrows()):
            if on_progress:
                on_progress(f"Scan {i + 1}/{deep_n}: {row['symbol']}")
            try:
                _entry, _htf, feats = load_symbol_bundle(client, row, cfg.analytics, i)
            except Exception as exc:  # noqa: BLE001
                _log(f"skip {row['symbol']}: {exc}")
                continue
            if not feats:
                continue
            decision = score_row(
                row,
                feats,
                btc_ret_24h=btc_ret,
                cfg=cfg.analytics,
                max_spread=cfg.universe.max_spread_bps,
            )
            rows.append(
                {
                    "symbol": row["symbol"],
                    "category": row["category"],
                    "turnover_24h": row["turnover_24h"],
                    "spread_bps": row.get("spread_bps"),
                    "price_change_pct_24h": row.get("price_change_pct_24h"),
                    "funding_rate": row.get("funding_rate"),
                    "open_interest": row.get("open_interest"),
                    "atr_pct": feats.get("atr_pct"),
                    "htf_slope": feats.get("htf_slope"),
                    "rsi": feats.get("rsi"),
                    "ret_24h": feats.get("ret_24h"),
                    "ret_7d": feats.get("ret_7d"),
                    "rvol": feats.get("rvol"),
                    "structure_score": feats.get("structure_score"),
                    "realized_vol": feats.get("realized_vol"),
                    "btc_ret_24h": btc_ret,
                    "score": decision.composite,
                    "accepted": decision.accepted,
                    "reasons": "|".join(decision.reasons),
                    **{f"p_{k}": v for k, v in decision.parts.items()},
                }
            )

    ranked = pd.DataFrame(rows)
    if ranked.empty:
        shortlist = ranked
    else:
        ranked = ranked.sort_values(
            ["accepted", "score", "turnover_24h"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        shortlist = ranked.loc[ranked["accepted"]].head(cfg.analytics.shortlist_n).copy()
        if shortlist.empty:
            # Fallback: top scores even if gates strict
            shortlist = ranked.head(cfg.analytics.shortlist_n).copy()
            shortlist["reasons"] = shortlist["reasons"] + "|fallback_top_score"

    if cfg.output.save_csv and not ranked.empty:
        ranked.to_csv(run_dir / "analytics_ranked.csv", index=False)
        shortlist.to_csv(run_dir / "shortlist.csv", index=False)

    if not quiet:
        _print_shortlist(shortlist, run_dir)
    _log(f"Done. Shortlist: {len(shortlist)}")
    return AnalyticsBundle(
        universe=universe,
        ranked=ranked,
        shortlist=shortlist,
        run_dir=run_dir,
    )


def _print_shortlist(shortlist: pd.DataFrame, run_dir: Path) -> None:
    table = Table(title="EdgeBot shortlist — analytical selection")
    for col in ("#", "symbol", "cat", "score", "turn24h", "atr%", "htf", "RS", "why"):
        table.add_column(col)

    if shortlist.empty:
        console.print("[red]Shortlist empty[/]")
        return

    for i, row in enumerate(shortlist.itertuples(index=False), start=1):
        why = str(row.reasons)
        tags = [p for p in why.split("|") if p.startswith("top:") or p in ("pass", "soft_penalty")]
        table.add_row(
            str(i),
            str(row.symbol),
            str(row.category),
            f"{row.score:.1f}",
            f"{row.turnover_24h/1e6:.1f}M",
            f"{(row.atr_pct or 0)*100:.2f}",
            f"{row.htf_slope:.4f}",
            f"{(row.ret_24h or 0) - (row.btc_ret_24h or 0):+.1f}",
            ",".join(tags[:4]) or why[:40],
        )
    console.print(table)
    console.print(f"[green]Saved →[/] {run_dir}")
