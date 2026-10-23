from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.io as pio

from edgebot.analytics.features import fetch_bars
from edgebot.analytics.universe import screen_tickers
from edgebot.bybit.client import BybitClient
from edgebot.config import AppConfig, data_dir, load_config
from edgebot.research.charts import artifact_from_opt
from edgebot.research.classify import classify_universe
from edgebot.research.optimize_cross import optimize_cross_symbol
from edgebot.research.pipeline import ProofBundle
from edgebot.research.proof import ProofGates, evaluate_proof


def run_cross_heavy_research(
    *,
    cfg: AppConfig | None = None,
    max_heavy: int = 12,
    quiet: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> ProofBundle:
    """
    Отдельный прогон: только тяжёлые монеты + чистые кресты EMA.
    Текущий Proof MA (heavy/fast) не трогает.
    """
    cfg = cfg or load_config()
    run_dir = data_dir() / "runs" / pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S_cross")
    run_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = run_dir / "charts"
    charts_dir.mkdir(exist_ok=True)

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        elif not quiet:
            print(msg, flush=True)

    bars_entry = max(cfg.analytics.bars_entry, 700)
    bars_htf = max(cfg.analytics.bars_htf, 350)
    gates = ProofGates(min_trades=8, target_winrate=0.55)
    artifacts: dict[str, Any] = {}

    with BybitClient() as client:
        universe = screen_tickers(client, cfg)
        _log(f"Universe: {len(universe)}")
        classified = classify_universe(universe, heavy_top_n=20, fast_min_abs_delta_pct=99, fast_top_n=0)
        heavy = classified[classified["bucket"] == "heavy"].head(max_heavy)
        _log(f"Cross-heavy set: {len(heavy)}")

        rows: list[dict] = []
        for i, row in enumerate(heavy.itertuples(index=False)):
            symbol = str(row.symbol)
            category = str(row.category)
            _log(f"[{i+1}/{len(heavy)}] CROSS {symbol}")
            try:
                entry = fetch_bars(
                    client, category, symbol, cfg.analytics.entry_tf, bars_entry, demo_seed=i + 11
                )
                htf = fetch_bars(
                    client, category, symbol, cfg.analytics.htf, bars_htf, demo_seed=i + 91
                )
            except Exception as exc:  # noqa: BLE001
                _log(f"skip {symbol}: {exc}")
                continue
            if len(entry) < 120:
                continue

            allow_short = category == "linear"
            opt = optimize_cross_symbol(entry, htf, allow_short=allow_short)
            all_m = opt.get("all") or opt["oos"]
            proof = evaluate_proof(
                opt["train"],
                opt["oos"],
                bucket="heavy",
                gates=gates,
                all_metrics=all_m,
            )
            params = opt.get("params") or {}
            wr_pct = float(proof.get("winrate_pct") or opt.get("winrate_pct") or 0)
            rows.append(
                {
                    "symbol": symbol,
                    "category": category,
                    "bucket": "heavy",
                    "strategy": "cross",
                    "turnover_24h": float(row.turnover_24h),
                    "delta_24h": float(row.price_change_pct_24h),
                    "spread_bps": row.spread_bps,
                    "whitelist": proof["whitelist"],
                    "emulator": proof["emulator"],
                    "verdict": proof["verdict"],
                    "verdict_short": proof.get("verdict_short", ""),
                    "headline": proof.get("headline", ""),
                    "proof": proof["proof"],
                    "proof_html": proof.get("proof_html", ""),
                    "fails": ",".join(proof["fails"]),
                    "reasons_ru": " | ".join(proof.get("reasons_ru") or []),
                    "ema_fast": params.get("ema_fast"),
                    "ema_slow": params.get("ema_slow"),
                    "atr_mult": params.get("atr_mult"),
                    "tp_r": params.get("take_profit_r"),
                    "htf_slope_min": params.get("min_htf_slope"),
                    "winrate_pct": wr_pct,
                    "trades_n": int(all_m.get("trades", 0) or 0),
                    "train_n": opt["train"]["trades"],
                    "train_wr": round(float(opt["train"]["winrate"]), 3),
                    "train_exp_r": round(float(opt["train"]["expectancy_r"]), 3),
                    "oos_n": opt["oos"]["trades"],
                    "oos_wr": round(float(opt["oos"]["winrate"]), 3),
                    "oos_exp_r": round(float(opt["oos"]["expectancy_r"]), 3),
                    "oos_pf": round(float(opt["oos"]["profit_factor"]), 3),
                    "opt_score": round(float(opt.get("score", -999)), 3),
                }
            )
            if opt.get("ok") and params:
                art = artifact_from_opt(
                    entry,
                    opt,
                    symbol=symbol,
                    category=category,
                    bucket="heavy",
                    proof=proof,
                )
                artifacts[symbol] = art
                if proof["whitelist"]:
                    pio.write_html(art["figures"]["price"], charts_dir / f"{symbol}_cross_price.html", auto_open=False)
                    pio.write_html(art["figures"]["equity"], charts_dir / f"{symbol}_cross_equity.html", auto_open=False)

    results = pd.DataFrame(rows)
    if not results.empty:
        results = results.sort_values(
            ["whitelist", "winrate_pct", "trades_n"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        whitelist = results[results["whitelist"]].copy()
    else:
        whitelist = results.copy()

    if cfg.output.save_csv:
        universe.to_csv(run_dir / "universe.csv", index=False)
        heavy.to_csv(run_dir / "heavy_set.csv", index=False)
        results.to_csv(run_dir / "cross_results.csv", index=False)
        whitelist.to_csv(run_dir / "cross_whitelist.csv", index=False)
        (run_dir / "cross_whitelist.json").write_text(
            json.dumps(whitelist.to_dict(orient="records"), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    _log(f"Cross done. WL={len(whitelist)} / {len(results)}")
    return ProofBundle(
        universe=universe,
        classified=heavy,
        results=results,
        whitelist=whitelist,
        emulator_queue=whitelist.copy(),
        run_dir=run_dir,
        artifacts=artifacts,
    )
