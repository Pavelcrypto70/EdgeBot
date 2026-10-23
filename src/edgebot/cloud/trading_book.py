from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from edgebot.analytics.features import fetch_bars
from edgebot.backtest.engine import simulate_signals
from edgebot.bybit.client import BybitClient
from edgebot.cloud.autonomous import PUBLIC_DIR, _read_json, _write_json
from edgebot.config import load_config
from edgebot.emulator.engine import PaperEmulator, _REASON_RU, _SIDE_RU
from edgebot.strategies.ema_ma import StrategyParams, generate_signals


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _params_from_row(row: dict[str, Any]) -> StrategyParams:
    name = str(row.get("strategy") or row.get("bucket") or "cross")
    if name not in {"heavy", "fast", "cross"}:
        name = "cross"
    return StrategyParams(
        name=name,
        ema_fast=int(row.get("ema_fast") or 20),
        ema_slow=int(row.get("ema_slow") or 50),
        atr_mult=float(row.get("atr_mult") or 1.2),
        take_profit_r=float(row.get("tp_r") or row.get("take_profit_r") or 1.2),
        min_htf_slope=float(row.get("htf_slope_min") or 0.0),
        allow_short=str(row.get("category") or "linear") == "linear",
    )


def _usd_trades_from_backtest(
    bars: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    notional: float,
    fee_rate: float,
) -> list[dict[str, Any]]:
    """Переводим R-сделки бэктеста в USDT при фиксированном объёме позиции."""
    out: list[dict[str, Any]] = []
    if trades is None or trades.empty or bars.empty:
        return out
    for t in trades.itertuples(index=False):
        entry = float(t.entry)
        if entry <= 0:
            continue
        size = notional / entry
        exit_px = float(t.exit)
        side = str(t.side)
        if side == "long":
            raw = (exit_px - entry) * size
        else:
            raw = (entry - exit_px) * size
        fee = notional * fee_rate * 2
        pnl = raw - fee
        out.append(
            {
                "symbol": "",  # заполним снаружи
                "side": _SIDE_RU.get(side, side.upper()),
                "side_raw": side,
                "entry": entry,
                "exit": exit_px,
                "pnl": round(pnl, 2),
                "reason": _REASON_RU.get(str(t.reason), str(t.reason)),
                "win": pnl > 0,
                "closed_at": str(getattr(t, "ts", "") or ""),
            }
        )
    return out


def update_trading_book(
    whitelist: list[dict[str, Any]],
    *,
    quiet: bool = False,
) -> dict[str, Any]:
    """
    Бумажная торговая книга для публичного сайта.
    1) Бэктест по актуальным параметрам WL → закрытые сделки в USDT
    2) Один live-тик эмулятора → открытые позиции / капитал
    """
    cfg = load_config()
    path = PUBLIC_DIR / "trading.json"
    margin = 100.0
    lev = 3.0
    notional = margin * lev
    start = 1000.0

    closed: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []

    def _log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    with BybitClient(timeout=20.0) as client:
        for row in whitelist:
            sym = str(row.get("symbol") or "")
            if not sym:
                continue
            cat = str(row.get("category") or "linear")
            try:
                entry = fetch_bars(client, cat, sym, cfg.analytics.entry_tf, 220)
                htf = fetch_bars(client, cat, sym, cfg.analytics.htf, 120)
            except Exception as exc:  # noqa: BLE001
                _log(f"trading skip {sym}: {exc}")
                continue
            if len(entry) < 80:
                continue
            params = _params_from_row(row)
            sigs = generate_signals(entry, htf, params)
            trades = simulate_signals(entry, sigs, fee_rate=0.00055)
            usd = _usd_trades_from_backtest(entry, trades, notional=notional, fee_rate=0.00055)
            for u in usd:
                u["symbol"] = sym
            # берём последние сделки, чтобы книга не раздувалась
            recent = usd[-12:]
            closed.extend(recent)
            wins = sum(1 for x in recent if x["win"])
            pnl_sum = sum(float(x["pnl"]) for x in recent)
            per_symbol.append(
                {
                    "symbol": sym,
                    "trades": len(recent),
                    "winrate_pct": round(100.0 * wins / len(recent), 1) if recent else 0.0,
                    "pnl": round(pnl_sum, 2),
                    "ema": f"{params.ema_fast}/{params.ema_slow}",
                    "strategy": params.name,
                }
            )
            _log(f"книга {sym}: {len(recent)} сделок · PnL {pnl_sum:+.2f} USDT")

        # Live-тик: открытые позиции по текущему рынку
        emu = PaperEmulator(
            starting_balance=start,
            order_margin_usdt=margin,
            default_leverage=lev,
        )
        emu.logs.clear()
        emu.load_whitelist(whitelist, replace=True)
        emu.start()
        try:
            live_snap = emu.tick(client, cfg=cfg)
        except Exception as exc:  # noqa: BLE001
            _log(f"live tick fail: {exc}")
            live_snap = emu.snapshot()

    closed = sorted(closed, key=lambda x: str(x.get("closed_at") or ""), reverse=True)[:80]
    realized = sum(float(x["pnl"]) for x in closed)
    wins = sum(1 for x in closed if x.get("win"))
    wr = round(100.0 * wins / len(closed), 1) if closed else 0.0
    unreal = float(live_snap.get("unrealized") or 0)
    equity = round(start + realized + unreal, 2)

    book = {
        "updated_at": _now_iso(),
        "status": "ok",
        "balance_start_usdt": start,
        "equity_usdt": equity,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unreal, 2),
        "winrate_pct": wr,
        "closed_n": len(closed),
        "open_n": int(live_snap.get("open_n") or 0),
        "order": {"margin_usdt": margin, "leverage": lev, "notional_usdt": notional},
        "open_positions": live_snap.get("positions") or [],
        "closed_trades": closed[:40],
        "by_symbol": sorted(per_symbol, key=lambda x: x["pnl"], reverse=True),
        "logs": (live_snap.get("logs") or [])[-30:],
        "note_ru": (
            "Бумажная статистика: закрытые сделки по параметрам whitelist на истории, "
            "открытые — live-тик эмулятора. Ордер 100$×3 = 300$ в позиции."
        ),
    }
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(path, book)
    _log(f"trading.json · equity {equity} · closed {len(closed)} · open {book['open_n']}")
    return book
