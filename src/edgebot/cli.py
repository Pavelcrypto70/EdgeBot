from __future__ import annotations

import argparse

from rich import print as rprint

from edgebot import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="edgebot", description="Bybit EdgeBot research desk")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_screen = sub.add_parser("screen", help="Fast ticker screener (liquidity + spread)")
    p_screen.add_argument("--top", type=int, default=None)

    p_an = sub.add_parser("analytics", help="Full multi-factor coin selection")
    p_an.add_argument("--top", type=int, default=None, help="Shortlist size")

    sub.add_parser("ui", help="Open screener desk (browser UI)")

    p_proof = sub.add_parser("proof", help="MA heavy/fast optimize + whitelist proof")
    p_proof.add_argument("--heavy", type=int, default=10)
    p_proof.add_argument("--fast", type=int, default=12)

    p_cross = sub.add_parser("crosses", help="Отдельно: кресты EMA только на тяжёлых")
    p_cross.add_argument("--heavy", type=int, default=12)

    p_auto = sub.add_parser(
        "autonomous",
        help="Облачный цикл: скан → diff whitelist → docs/data для GitHub Pages",
    )
    p_auto.add_argument("--heavy", type=int, default=10)
    p_auto.add_argument("--fast", type=int, default=8)
    p_auto.add_argument("--no-proof", action="store_true")
    p_auto.add_argument("--no-cross", action="store_true")
    p_auto.add_argument(
        "--reset-trading",
        action="store_true",
        help="Обнулить торговую книгу (1000 USDT, ордер 300$×3)",
    )

    p_book = sub.add_parser("trading-book", help="Обновить/сбросить публичную торговую книгу")
    p_book.add_argument("--reset", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "screen":
        from edgebot.bybit.client import BybitClient
        from edgebot.analytics.universe import screen_tickers
        from edgebot.config import load_config

        cfg = load_config()
        if args.top:
            cfg.universe.top_n_raw = args.top
        with BybitClient() as client:
            df = screen_tickers(client, cfg)
        cols = [
            "symbol",
            "category",
            "turnover_24h",
            "spread_bps",
            "price_change_pct_24h",
            "funding_rate",
        ]
        show = [c for c in cols if c in df.columns]
        rprint(df[show].head(60).to_string(index=False))
        return

    if args.cmd == "analytics":
        from edgebot.analytics.pipeline import run_analytics

        bundle = run_analytics(top=args.top)
        rprint(
            {
                "universe": len(bundle.universe),
                "ranked": len(bundle.ranked),
                "shortlist": len(bundle.shortlist),
                "run_dir": str(bundle.run_dir),
            }
        )
        return

    if args.cmd == "ui":
        from edgebot.ui.app import run_ui

        run_ui()
        return

    if args.cmd == "proof":
        from edgebot.research.pipeline import run_proof_research

        bundle = run_proof_research(max_heavy=args.heavy, max_fast=args.fast, quiet=False)
        rprint(
            {
                "researched": len(bundle.results),
                "whitelist": len(bundle.whitelist),
                "emulator": len(bundle.emulator_queue),
                "run_dir": str(bundle.run_dir),
            }
        )
        if not bundle.whitelist.empty:
            cols = [
                "symbol",
                "bucket",
                "ema_fast",
                "ema_slow",
                "oos_n",
                "oos_wr",
                "oos_exp_r",
                "verdict",
            ]
            rprint(bundle.whitelist[cols].to_string(index=False))
        return

    if args.cmd == "crosses":
        from edgebot.research.pipeline_cross import run_cross_heavy_research

        bundle = run_cross_heavy_research(max_heavy=args.heavy, quiet=False)
        rprint(
            {
                "mode": "cross_heavy",
                "researched": len(bundle.results),
                "whitelist": len(bundle.whitelist),
                "run_dir": str(bundle.run_dir),
            }
        )
        if not bundle.results.empty:
            cols = ["symbol", "ema_fast", "ema_slow", "winrate_pct", "trades_n", "whitelist", "verdict"]
            rprint(bundle.results[cols].head(20).to_string(index=False))
        return

    if args.cmd == "autonomous":
        from edgebot.cloud.autonomous import run_autonomous_cycle
        from edgebot.cloud.trading_book import reset_trading_book

        if args.reset_trading:
            reset_trading_book(quiet=False)

        live = run_autonomous_cycle(
            max_heavy=args.heavy,
            max_fast=args.fast,
            do_proof=not args.no_proof,
            do_cross=not args.no_cross,
            quiet=False,
        )
        rprint(
            {
                "updated_at": live.get("updated_at"),
                "whitelist_n": live.get("whitelist_n"),
                "added": live.get("last_added"),
                "removed": live.get("last_removed"),
            }
        )
        return

    if args.cmd == "trading-book":
        import json
        from pathlib import Path

        from edgebot.cloud.autonomous import PUBLIC_DIR
        from edgebot.cloud.trading_book import reset_trading_book, update_trading_book

        if args.reset:
            book = reset_trading_book(quiet=False)
            rprint(
                {
                    "reset": True,
                    "equity": book.get("equity_usdt"),
                    "closed_n": book.get("closed_n"),
                    "open_n": book.get("open_n"),
                    "order": book.get("order"),
                }
            )
            return
        wl_path = PUBLIC_DIR / "whitelist.json"
        wl = json.loads(wl_path.read_text(encoding="utf-8")) if wl_path.exists() else []
        book = update_trading_book(wl, quiet=False, reset=False)
        rprint(
            {
                "equity": book.get("equity_usdt"),
                "closed_n": book.get("closed_n"),
                "open_n": book.get("open_n"),
                "order": book.get("order"),
            }
        )
        return

    parser.error(f"unknown command {args.cmd}")


if __name__ == "__main__":
    main()
