from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edgebot.bybit.client import BybitClient
from edgebot.cloud.autonomous import PUBLIC_DIR, _read_json, _write_json
from edgebot.config import load_config
from edgebot.emulator.engine import BotSpec, ClosedTrade, PaperEmulator, Position

# Ордер 300 USDT в позиции при плече ×3 → маржа 100 USDT
ORDER_NOTIONAL = 300.0
LEVERAGE = 3.0
ORDER_MARGIN = ORDER_NOTIONAL / LEVERAGE  # 100
START_BALANCE = 1000.0
# bump: сброс last_signal_key после смены режима fast (иначе старые demo-ключи глушат входы)
SIGNAL_MODE_V = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_book() -> dict[str, Any]:
    return {
        "updated_at": _now_iso(),
        "status": "ok",
        "balance_start_usdt": START_BALANCE,
        "equity_usdt": START_BALANCE,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "winrate_pct": 0.0,
        "closed_n": 0,
        "open_n": 0,
        "order": {
            "notional_usdt": ORDER_NOTIONAL,
            "leverage": LEVERAGE,
            "margin_usdt": ORDER_MARGIN,
        },
        "open_positions": [],
        "closed_trades": [],
        "by_symbol": [],
        "logs": [],
        "note_ru": (
            f"Чистый старт: {START_BALANCE:.0f} USDT, ордер {ORDER_NOTIONAL:.0f} USDT "
            f"(плечо ×{int(LEVERAGE)}, маржа {ORDER_MARGIN:.0f}$). "
            "Закрытые сделки только из живого эфира, без бэктеста."
        ),
    }


def reset_trading_book(*, quiet: bool = False) -> dict[str, Any]:
    """Обнулить закрытые/открытые, капитал 1000, ордер 300 USDT ×3."""
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    book = _empty_book()
    state = {
        "wallet": START_BALANCE,
        "realized_pnl": 0.0,
        "positions": {},
        "history": [],
        "logs": [
            f"[{_now_iso()}] сброс книги · {START_BALANCE:.0f} USDT · "
            f"ордер {ORDER_NOTIONAL:.0f}$ ×{int(LEVERAGE)}"
        ],
        "last_signal_key": {},
        "ticks": 0,
        "signal_mode_v": SIGNAL_MODE_V,
    }
    _write_json(PUBLIC_DIR / "trading.json", book)
    _write_json(PUBLIC_DIR / "trading_state.json", state)
    if not quiet:
        print("торговая книга обнулена", flush=True)
    return book


def _restore_emu(state: dict[str, Any]) -> PaperEmulator:
    emu = PaperEmulator(
        starting_balance=START_BALANCE,
        order_margin_usdt=ORDER_MARGIN,
        default_leverage=LEVERAGE,
    )
    emu.logs.clear()
    emu.wallet = float(state.get("wallet", START_BALANCE))
    emu.realized_pnl = float(state.get("realized_pnl", 0.0))
    emu.ticks = int(state.get("ticks", 0))
    emu._last_signal_key = dict(state.get("last_signal_key") or {})
    emu.history = []
    for h in state.get("history") or []:
        try:
            emu.history.append(
                ClosedTrade(
                    symbol=str(h["symbol"]),
                    side=str(h["side"]),
                    entry=float(h["entry"]),
                    exit=float(h["exit"]),
                    size=float(h["size"]),
                    pnl=float(h["pnl"]),
                    reason=str(h["reason"]),
                    opened_at=str(h.get("opened_at") or ""),
                    closed_at=str(h.get("closed_at") or ""),
                    win=bool(h.get("win")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    emu.positions = {}
    for sym, p in (state.get("positions") or {}).items():
        try:
            pos = Position(
                symbol=str(p["symbol"]),
                category=str(p.get("category") or "linear"),
                side=str(p["side"]),
                size=float(p["size"]),
                entry=float(p["entry"]),
                stop=float(p["stop"]),
                take=float(p["take"]),
                leverage=float(p.get("leverage") or LEVERAGE),
                margin=float(p["margin"]),
                risk=float(p.get("risk") or 0.0),
                opened_at=str(p.get("opened_at") or ""),
                mark=float(p.get("mark") or p["entry"]),
                unrealized=float(p.get("unrealized") or 0.0),
            )
            emu.positions[str(sym)] = pos
        except (KeyError, TypeError, ValueError):
            continue
    for line in state.get("logs") or []:
        emu.logs.append(str(line))
    return emu


def _dump_state(emu: PaperEmulator) -> dict[str, Any]:
    return {
        "wallet": emu.wallet,
        "realized_pnl": emu.realized_pnl,
        "ticks": emu.ticks,
        "signal_mode_v": SIGNAL_MODE_V,
        "last_signal_key": dict(emu._last_signal_key),
        "history": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry": t.entry,
                "exit": t.exit,
                "size": t.size,
                "pnl": t.pnl,
                "reason": t.reason,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
                "win": t.win,
            }
            for t in emu.history[-200:]
        ],
        "positions": {
            sym: {
                "symbol": p.symbol,
                "category": p.category,
                "side": p.side,
                "size": p.size,
                "entry": p.entry,
                "stop": p.stop,
                "take": p.take,
                "leverage": p.leverage,
                "margin": p.margin,
                "risk": p.risk,
                "opened_at": p.opened_at,
                "mark": p.mark,
                "unrealized": p.unrealized,
            }
            for sym, p in emu.positions.items()
        },
        "logs": list(emu.logs[-120:]),
    }


def _book_from_emu(emu: PaperEmulator) -> dict[str, Any]:
    snap = emu.snapshot()
    closed = list(snap.get("history") or [])
    by_sym: dict[str, dict[str, Any]] = {}
    for t in emu.history:
        s = by_sym.setdefault(
            t.symbol,
            {"symbol": t.symbol, "trades": 0, "wins": 0, "pnl": 0.0},
        )
        s["trades"] += 1
        s["wins"] += 1 if t.win else 0
        s["pnl"] += float(t.pnl)
    by_symbol = []
    for s in by_sym.values():
        n = int(s["trades"])
        by_symbol.append(
            {
                "symbol": s["symbol"],
                "trades": n,
                "winrate_pct": round(100.0 * s["wins"] / n, 1) if n else 0.0,
                "pnl": round(s["pnl"], 2),
                "ema": "—",
                "strategy": "live",
            }
        )
    by_symbol.sort(key=lambda x: x["pnl"], reverse=True)

    # подтянуть EMA / bucket из ботов
    for row in by_symbol:
        bot = emu.bots.get(row["symbol"])
        if bot:
            row["ema"] = f"{bot.ema_fast}/{bot.ema_slow}"
            row["strategy"] = bot.strategy
            row["bucket"] = bot.bucket or (
                bot.strategy if bot.strategy in {"heavy", "fast"} else row.get("bucket")
            )

    by_symbol.sort(
        key=lambda x: (
            0 if x.get("bucket") == "heavy" else 1 if x.get("bucket") == "fast" else 2,
            -float(x.get("pnl") or 0),
        )
    )

    return {
        "updated_at": _now_iso(),
        "status": "ok",
        "balance_start_usdt": START_BALANCE,
        "equity_usdt": snap["equity"],
        "realized_pnl": snap["realized"],
        "unrealized_pnl": snap["unrealized"],
        "winrate_pct": snap["winrate"],
        "closed_n": snap["closed_n"],
        "open_n": snap["open_n"],
        "order": {
            "notional_usdt": ORDER_NOTIONAL,
            "leverage": LEVERAGE,
            "margin_usdt": ORDER_MARGIN,
        },
        "open_positions": snap.get("positions") or [],
        "closed_trades": closed,
        "by_symbol": by_symbol,
        "logs": snap.get("logs") or [],
        "bars_source": getattr(emu, "last_bars_source", "unknown"),
        "note_ru": (
            f"Живой эфир по whitelist: старт {START_BALANCE:.0f} USDT, "
            f"ордер {ORDER_NOTIONAL:.0f} USDT (×{int(LEVERAGE)}). "
            "Прогон входов ≈ каждую ~1 мин. Fast = крест+откат к EMA. "
            "Входы только по живым свечам Bybit; при 403/demo — пропуск."
            + (
                f" Сейчас бары: {getattr(emu, 'last_bars_source', '?')}."
                if getattr(emu, "last_bars_source", None)
                else ""
            )
        ),
    }


def update_trading_book(
    whitelist: list[dict[str, Any]],
    *,
    quiet: bool = False,
    reset: bool = False,
) -> dict[str, Any]:
    """Живая книга: только эмулятор + сохранение состояния между сканами."""
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    if reset:
        reset_trading_book(quiet=quiet)

    state_path = PUBLIC_DIR / "trading_state.json"
    state = _read_json(state_path, None)
    if not isinstance(state, dict):
        reset_trading_book(quiet=quiet)
        state = _read_json(state_path, {})

    emu = _restore_emu(state if isinstance(state, dict) else {})
    # всегда актуальные размеры ордера
    emu.order_margin_usdt = ORDER_MARGIN
    emu.default_leverage = LEVERAGE
    emu.starting_balance = START_BALANCE

    n = emu.load_whitelist(whitelist, replace=True)
    # BotSpec.leverage берётся из default_leverage эмулятора при load_whitelist

    prev_mode = int((state or {}).get("signal_mode_v") or 0) if isinstance(state, dict) else 0
    if prev_mode < SIGNAL_MODE_V:
        emu._last_signal_key.clear()
        # снять demo-открытия (~$90–110), чтобы не засорять книгу
        dropped = 0
        for sym, pos in list(emu.positions.items()):
            emu.wallet += float(pos.margin)
            del emu.positions[sym]
            dropped += 1
        emu.log(
            f"mode v{SIGNAL_MODE_V}: сброс меток + снято открытых {dropped} "
            f"(fast=крест+откат; входы только с живого Bybit, не demo)"
        )

    if not emu.running:
        emu.start()

    cfg = load_config()

    def _log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    _log(f"live книга · очередь {n} · ордер {ORDER_NOTIONAL:.0f}$ ×{int(LEVERAGE)}")
    with BybitClient(timeout=20.0) as client:
        try:
            emu.tick(client, cfg=cfg)
        except Exception as exc:  # noqa: BLE001
            emu.log(f"ошибка тика: {exc}")
            _log(f"live tick fail: {exc}")

    book = _book_from_emu(emu)
    _write_json(PUBLIC_DIR / "trading.json", book)
    _write_json(state_path, _dump_state(emu))
    _log(
        f"trading.json · equity {book['equity_usdt']} · "
        f"closed {book['closed_n']} · open {book['open_n']}"
    )
    return book
