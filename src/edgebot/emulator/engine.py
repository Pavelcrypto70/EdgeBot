from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from edgebot.analytics.features import fetch_bars, fetch_last_price
from edgebot.bybit.client import BybitClient
from edgebot.config import AppConfig, data_dir, load_config
from edgebot.strategies.ema_ma import StrategyParams, generate_signals

# после стопа не долбим ту же монету (минуты)
COOLDOWN_AFTER_STOP_MIN = 90
# серия стопов подряд → длинный блэклист
STREAK_STOPS_FOR_BLACKLIST = 3
BLACKLIST_AFTER_STREAK_MIN = 360


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.strptime(str(raw)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass(slots=True)
class BotSpec:
    symbol: str
    category: str
    strategy: str
    ema_fast: int
    ema_slow: int
    atr_mult: float
    take_profit_r: float
    min_htf_slope: float = 0.0
    leverage: float = 3.0
    proof_wr: float = 0.0
    bucket: str = ""

    def params(self) -> StrategyParams:
        # Режим сигналов: bucket важнее strategy из бэктеста.
        # Быстрые всегда в режиме fast (крест + откат), иначе live почти молчит.
        bucket = (self.bucket or "").lower()
        name = (self.strategy or "").lower()
        if bucket == "fast":
            name = "fast"
        elif name not in {"heavy", "fast", "cross"}:
            name = "heavy" if bucket == "heavy" else "cross"
        return StrategyParams(
            name=name,
            ema_fast=int(self.ema_fast),
            ema_slow=int(self.ema_slow),
            atr_mult=float(self.atr_mult),
            take_profit_r=float(self.take_profit_r),
            min_htf_slope=float(self.min_htf_slope or 0.0),
            allow_short=self.category == "linear",
        )


@dataclass
class Position:
    symbol: str
    category: str
    side: str
    size: float
    entry: float
    stop: float
    take: float
    leverage: float
    margin: float
    risk: float
    opened_at: str
    mark: float = 0.0
    unrealized: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.size * self.mark)

    def update_mark(self, mark: float) -> None:
        self.mark = float(mark)
        if self.side == "long":
            self.unrealized = (self.mark - self.entry) * self.size
        else:
            self.unrealized = (self.entry - self.mark) * self.size


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry: float
    exit: float
    size: float
    pnl: float
    reason: str
    opened_at: str
    closed_at: str
    win: bool


_REASON_RU = {
    "stop": "стоп",
    "take": "тейк",
    "eod": "закрытие",
    "manual": "вручную",
}

_SIDE_RU = {"long": "ЛОНГ", "short": "ШОРТ"}

_STRAT_RU = {"heavy": "тяжёлая", "fast": "быстрая", "cross": "крест"}


@dataclass
class PaperEmulator:
    """Бумажный эмулятор: открывает сделки по параметрам whitelist на живых свечах."""

    starting_balance: float = 1000.0  # общий баланс USDT
    order_margin_usdt: float = 100.0  # маржа на ордер (100$ × плечо 3 = 300$ в позиции)
    default_leverage: float = 3.0  # плечо x3
    fee_rate: float = 0.00055
    max_positions: int = 10
    bars_entry: int = 160
    bars_htf: int = 100
    entry_tf: int = 15
    htf: int = 60

    wallet: float = 1000.0
    realized_pnl: float = 0.0
    bots: dict[str, BotSpec] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    history: list[ClosedTrade] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    running: bool = False
    ticks: int = 0
    _last_signal_key: dict[str, str] = field(default_factory=dict)
    # symbol -> unix ts до которого вход запрещён
    _cooldown_until: dict[str, float] = field(default_factory=dict)
    _stop_streak: dict[str, int] = field(default_factory=dict)
    _started_at: str | None = None
    last_bars_source: str = "unknown"  # bybit | binance | demo | mixed
    _demo_entries_skipped: int = 0
    _sources_seen: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.wallet = float(self.starting_balance)
        pos = self.order_margin_usdt * self.default_leverage
        self.log(
            f"эмулятор готов · баланс {self.starting_balance:.0f} USDT · "
            f"ордер {self.order_margin_usdt:.0f}$ ×{int(self.default_leverage)} "
            f"= {pos:.0f}$ в позиции"
        )

    def log(self, msg: str) -> None:
        line = f"[{_now()}] {msg}"
        self.logs.append(line)
        if len(self.logs) > 400:
            self.logs = self.logs[-300:]

    def clear_queue(self) -> None:
        self.bots.clear()

    def load_whitelist(self, rows: list[dict[str, Any]], *, replace: bool = True) -> int:
        if replace:
            self.bots.clear()
        n = 0
        for r in rows:
            if not r.get("whitelist") and not r.get("emulator"):
                continue
            sym = str(r.get("symbol") or "")
            if not sym:
                continue
            try:
                fast = int(r.get("ema_fast") or 20)
                slow = int(r.get("ema_slow") or 50)
                if fast >= slow:
                    continue
                bucket = str(r.get("bucket") or "").lower()
                strat = str(r.get("strategy") or "").lower()
                # fast отключён: только средние/медленные (heavy + кресты)
                if bucket == "fast" or strat == "fast":
                    continue
                if bucket == "heavy":
                    strat = strat if strat in {"heavy", "cross"} else "cross"
                elif strat not in {"heavy", "cross"}:
                    strat = "cross"
                self.bots[sym] = BotSpec(
                    symbol=sym,
                    category=str(r.get("category") or "linear"),
                    strategy=strat,
                    ema_fast=fast,
                    ema_slow=slow,
                    atr_mult=float(r.get("atr_mult") or 1.2),
                    take_profit_r=float(r.get("tp_r") or r.get("take_profit_r") or 1.2),
                    min_htf_slope=float(r.get("htf_slope_min") or r.get("min_htf_slope") or 0.0),
                    leverage=float(self.default_leverage),
                    proof_wr=float(r.get("winrate_pct") or 0.0),
                    bucket=bucket or strat,
                )
                n += 1
            except (TypeError, ValueError):
                continue
        self.log(f"очередь загружена · {n} монет из whitelist")
        return n

    def start(self) -> None:
        if not self.bots:
            self.log("старт отменён · очередь пуста")
            return
        self.running = True
        self._started_at = _now()
        self.log(f"В ЭФИРЕ · старт · {len(self.bots)} монет в работе")

    def stop(self) -> None:
        self.running = False
        self.log("эфир остановлен")

    def reset_account(self) -> None:
        self.positions.clear()
        self.history.clear()
        self.realized_pnl = 0.0
        self.wallet = float(self.starting_balance)
        self._last_signal_key.clear()
        self._cooldown_until.clear()
        self._stop_streak.clear()
        self.ticks = 0

    def _on_cooldown(self, symbol: str) -> bool:
        until = float(self._cooldown_until.get(symbol) or 0)
        return until > datetime.now(timezone.utc).timestamp()

    def _arm_cooldown(self, symbol: str, minutes: int, *, why: str) -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))
        prev = float(self._cooldown_until.get(symbol) or 0)
        ts = until.timestamp()
        if ts > prev:
            self._cooldown_until[symbol] = ts
            self.log(f"блэклист {symbol} · {minutes} мин · {why}")
        self.log(f"счёт сброшен · {self.wallet:.2f} USDT")

    @property
    def margin_used(self) -> float:
        return sum(p.margin for p in self.positions.values())

    @property
    def unrealized(self) -> float:
        return sum(p.unrealized for p in self.positions.values())

    @property
    def equity(self) -> float:
        # Крупная цифра сверху: старт ± зафиксированный ± плавающий по открытым.
        # (wallet уже без маржи открытых — маржу возвращаем в капитал)
        return self.wallet + self.margin_used + self.unrealized

    @property
    def available(self) -> float:
        # Маржа уже списана с wallet при открытии — свободно = остаток кошелька
        return max(0.0, self.wallet)

    def winrate(self) -> float:
        if not self.history:
            return 0.0
        return sum(1 for t in self.history if t.win) / len(self.history)

    def snapshot(self) -> dict[str, Any]:
        pos_rows = []
        for p in self.positions.values():
            pos_rows.append(
                {
                    "symbol": p.symbol,
                    "side": _SIDE_RU.get(p.side, p.side.upper()),
                    "side_raw": p.side,
                    "size": round(p.size, 6),
                    "value": round(p.notional, 2),
                    "entry": p.entry,
                    "mark": p.mark,
                    "pnl": round(p.unrealized, 2),
                    "pnl_pct": round((p.unrealized / p.margin * 100) if p.margin else 0.0, 2),
                    "lev": f"x{int(p.leverage)}",
                    "margin": round(p.margin, 2),
                    "stop": p.stop,
                    "take": p.take,
                }
            )
        hist_rows = []
        for t in reversed(self.history[-40:]):
            hist_rows.append(
                {
                    "symbol": t.symbol,
                    "side": _SIDE_RU.get(t.side, t.side.upper()),
                    "pnl": round(t.pnl, 2),
                    "reason": _REASON_RU.get(t.reason, t.reason),
                    "when": t.closed_at,
                    "win": t.win,
                }
            )
        return {
            "running": self.running,
            "ticks": self.ticks,
            "queue_n": len(self.bots),
            "open_n": len(self.positions),
            "equity": round(self.equity, 2),
            "wallet": round(self.wallet, 2),
            "available": round(self.available, 2),
            "in_positions": round(self.margin_used, 2),
            "realized": round(self.realized_pnl, 2),
            "unrealized": round(self.unrealized, 2),
            "winrate": round(self.winrate() * 100, 1),
            "closed_n": len(self.history),
            "started_at": self._started_at,
            "order_margin": self.order_margin_usdt,
            "order_notional": self.order_margin_usdt * self.default_leverage,
            "leverage": self.default_leverage,
            "positions": pos_rows,
            "history": hist_rows,
            "queue": [
                {
                    "symbol": b.symbol,
                    "strategy": _STRAT_RU.get(b.strategy, b.strategy),
                    "ma": f"{b.ema_fast}/{b.ema_slow}",
                    "wr": b.proof_wr,
                    "open": b.symbol in self.positions,
                }
                for b in self.bots.values()
            ],
            "logs": list(self.logs[-80:]),
        }

    def _ticker_map(self, client: BybitClient, category: str, cache: dict[str, dict[str, float]]) -> dict[str, float]:
        if category in cache:
            return cache[category]
        out: dict[str, float] = {}
        try:
            for it in client.tickers(category):
                sym = str(it.get("symbol") or "")
                raw = it.get("lastPrice") or it.get("markPrice")
                try:
                    out[sym] = float(raw)
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass
        cache[category] = out
        return out

    def _resolve_mark(
        self,
        client: BybitClient,
        category: str,
        symbol: str,
        marks_cache: dict[str, dict[str, float]],
        bars: Any | None = None,
    ) -> float | None:
        """Марка для PnL: Bybit тикер → OKX/Binance → close последних баров."""
        mmap = self._ticker_map(client, category, marks_cache)
        mark = mmap.get(symbol)
        if mark is not None and mark > 0:
            return float(mark)
        px = fetch_last_price(symbol, category)
        if px is not None and px > 0:
            marks_cache.setdefault(category, {})[symbol] = float(px)
            return float(px)
        if bars is not None and len(bars) and not bool(bars.attrs.get("edgebot_demo")):
            try:
                return float(bars["close"].iloc[-1])
            except Exception:
                return None
        return None

    def _close(self, pos: Position, price: float, reason: str) -> None:
        fee = abs(pos.size * price) * self.fee_rate
        if pos.side == "long":
            pnl = (price - pos.entry) * pos.size - fee
        else:
            pnl = (pos.entry - price) * pos.size - fee
        self.wallet += pos.margin + pnl
        self.realized_pnl += pnl
        closed = ClosedTrade(
            symbol=pos.symbol,
            side=pos.side,
            entry=pos.entry,
            exit=price,
            size=pos.size,
            pnl=pnl,
            reason=reason,
            opened_at=pos.opened_at,
            closed_at=_now(),
            win=pnl > 0,
        )
        self.history.append(closed)
        del self.positions[pos.symbol]
        # после стопа — пауза; серия стопов → длинный блэклист
        if reason == "stop":
            streak = int(self._stop_streak.get(pos.symbol) or 0) + 1
            self._stop_streak[pos.symbol] = streak
            if streak >= STREAK_STOPS_FOR_BLACKLIST:
                self._arm_cooldown(
                    pos.symbol,
                    BLACKLIST_AFTER_STREAK_MIN,
                    why=f"серия стопов ×{streak}",
                )
                self._stop_streak[pos.symbol] = 0
            else:
                self._arm_cooldown(
                    pos.symbol,
                    COOLDOWN_AFTER_STOP_MIN,
                    why="стоп",
                )
        else:
            self._stop_streak[pos.symbol] = 0
        sign = "+" if pnl >= 0 else ""
        reason_ru = _REASON_RU.get(reason, reason)
        side_ru = _SIDE_RU.get(pos.side, pos.side)
        self.log(
            f"{reason_ru.upper()} {side_ru} {pos.symbol} @ {price:.6g} "
            f"результат {sign}{pnl:.2f} USDT"
        )

    def _try_open(self, bot: BotSpec, sig: pd.Series, mark: float) -> bool:
        if bot.symbol in self.positions:
            return False
        if len(self.positions) >= self.max_positions:
            return False
        if mark <= 0:
            return False
        risk_px = abs(float(sig["entry"]) - float(sig["stop"]))
        if risk_px <= 0:
            return False

        lev = float(self.default_leverage)
        margin = float(self.order_margin_usdt)  # 100$ маржи
        notional = margin * lev  # 300$ в позиции
        if margin + notional * self.fee_rate > self.available:
            self.log(
                f"пропуск {bot.symbol} · мало свободно "
                f"{self.available:.2f} USDT (нужно ~{margin:.2f} маржи)"
            )
            return False

        size = notional / mark
        fee = notional * self.fee_rate
        self.wallet -= margin + fee
        side = str(sig["side"])
        entry = mark
        stop = float(sig["stop"]) + (mark - float(sig["entry"]))
        take = float(sig["take"]) + (mark - float(sig["entry"]))
        pos = Position(
            symbol=bot.symbol,
            category=bot.category,
            side=side,
            size=size,
            entry=entry,
            stop=stop,
            take=take,
            leverage=lev,
            margin=margin,
            risk=risk_px,
            opened_at=_now(),
            mark=mark,
        )
        pos.update_mark(mark)
        self.positions[bot.symbol] = pos
        side_ru = _SIDE_RU.get(side, side)
        self.log(
            f"ОТКРЫТИЕ {side_ru} {bot.symbol} @ {mark:.6g} · "
            f"маржа {margin:.0f}$ ×{int(lev)} = {notional:.0f}$ в позиции · "
            f"стоп {stop:.6g} · тейк {take:.6g} · "
            f"EMA {bot.ema_fast}/{bot.ema_slow}"
        )
        return True

    def tick(self, client: BybitClient | None = None, *, cfg: AppConfig | None = None) -> dict[str, Any]:
        if not self.running:
            return self.snapshot()
        cfg = cfg or load_config()
        self.entry_tf = int(cfg.analytics.entry_tf)
        self.htf = int(cfg.analytics.htf)
        own = client is None
        client = client or BybitClient(timeout=12.0)
        self.ticks += 1
        marks_cache: dict[str, dict[str, float]] = {}
        try:
            # 1) exits: только марка + свечи СТРОГО после opened_at
            # (раньше брали last-8 любых баров → мгновенный «стоп» и цикл DOOD)
            for sym, pos in list(self.positions.items()):
                try:
                    bars = fetch_bars(
                        client, pos.category, sym, self.entry_tf, 16
                    )
                except Exception:
                    bars = None
                if bars is not None and bool(bars.attrs.get("edgebot_demo")):
                    bars = None
                opened_dt = _parse_ts(pos.opened_at)
                if bars is not None and len(bars) >= 2 and "ts" in bars.columns and opened_dt:
                    # только бары после входа (не старше чем opened)
                    after = bars[pd.to_datetime(bars["ts"], utc=True) >= opened_dt]
                    # не более 3 последних закрытых после входа
                    after = after.tail(3)
                    for j in range(len(after)):
                        hi = float(after["high"].iloc[j])
                        lo = float(after["low"].iloc[j])
                        if pos.side == "long":
                            if lo <= pos.stop:
                                self._close(pos, pos.stop, "stop")
                                break
                            if hi >= pos.take:
                                self._close(pos, pos.take, "take")
                                break
                        else:
                            if hi >= pos.stop:
                                self._close(pos, pos.stop, "stop")
                                break
                            if lo <= pos.take:
                                self._close(pos, pos.take, "take")
                                break
                    if sym not in self.positions:
                        continue
                mark = self._resolve_mark(client, pos.category, sym, marks_cache, bars)
                if mark is None:
                    self.log(f"нет марки {sym} — PnL не обновлён в этом тике")
                    continue
                if sym not in self.positions:
                    continue
                pos = self.positions[sym]
                pos.update_mark(mark)
                if pos.side == "long":
                    if mark <= pos.stop:
                        self._close(pos, pos.stop, "stop")
                    elif mark >= pos.take:
                        self._close(pos, pos.take, "take")
                else:
                    if mark >= pos.stop:
                        self._close(pos, pos.stop, "stop")
                    elif mark <= pos.take:
                        self._close(pos, pos.take, "take")

            # 2) входы: только heavy/cross, узкое окно, с кулдауном после стопа
            self._demo_entries_skipped = 0
            self._sources_seen = set()
            for bot in list(self.bots.values()):
                if bot.symbol in self.positions:
                    continue
                if self._on_cooldown(bot.symbol):
                    continue
                if len(self.positions) >= self.max_positions:
                    break
                mode = bot.params().name
                if mode == "fast":
                    continue
                lookback = 2  # только свежий крест на 1–2 барах
                demo_seed = (abs(hash(bot.symbol)) % 9000) + 1
                try:
                    entry = fetch_bars(
                        client,
                        bot.category,
                        bot.symbol,
                        self.entry_tf,
                        self.bars_entry,
                        demo_seed=demo_seed,
                    )
                    htf = fetch_bars(
                        client,
                        bot.category,
                        bot.symbol,
                        self.htf,
                        self.bars_htf,
                        demo_seed=demo_seed + 77,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.log(f"нет данных {bot.symbol}: {exc}")
                    continue
                src = str(entry.attrs.get("edgebot_source") or ("demo" if entry.attrs.get("edgebot_demo") else "?"))
                self._sources_seen.add(src)
                if bool(entry.attrs.get("edgebot_demo")):
                    self._demo_entries_skipped += 1
                    errs = entry.attrs.get("edgebot_fallback_errors")
                    if errs and self._demo_entries_skipped <= 2:
                        self.log(f"нет живых баров {bot.symbol}: {errs}")
                    continue
                if len(entry) < 60:
                    continue
                sigs = generate_signals(entry, htf, bot.params())
                if sigs.empty:
                    continue
                min_i = max(0, len(entry) - lookback)
                window = sigs[sigs["i"].astype(int) >= min_i]
                if window.empty:
                    continue
                seen = self._last_signal_key.get(bot.symbol)
                pick = None
                pick_key = None
                for _, row in window.iloc[::-1].iterrows():
                    key = f"{int(row['i'])}:{row['side']}:{float(row['entry']):.8g}"
                    if key == seen:
                        break
                    pick = row
                    pick_key = key
                    break
                if pick is None or pick_key is None:
                    continue
                mark = self._resolve_mark(
                    client, bot.category, bot.symbol, marks_cache, entry
                )
                if mark is None:
                    mark = float(entry["close"].iloc[-1])
                opened = self._try_open(bot, pick, mark)
                self._last_signal_key[bot.symbol] = pick_key
                if opened:
                    self.log(
                        f"вход по сигналу бара i={int(pick['i'])} · {bot.symbol} · "
                        f"режим {mode} · {src}"
                    )

            if not self._sources_seen:
                self.last_bars_source = "unknown"
            elif len(self._sources_seen) == 1:
                self.last_bars_source = next(iter(self._sources_seen))
            else:
                self.last_bars_source = "mixed:" + "+".join(sorted(self._sources_seen))
            if self._demo_entries_skipped:
                self.log(
                    f"пропуск входов · demo-бары · {self._demo_entries_skipped} монет · "
                    f"источник тика: {self.last_bars_source}"
                )

            if self.ticks % 5 == 1:
                self.log(
                    f"пульс · капитал {self.equity:.2f} USDT · "
                    f"открыто {len(self.positions)} · очередь {len(self.bots)}"
                )
        finally:
            if own:
                client.close()
        return self.snapshot()

    def load_latest_run_whitelist(self) -> int:
        """Подтянуть последний whitelist с диска (proof/cross), если очередь пуста."""
        runs = data_dir() / "runs"
        if not runs.exists():
            return 0
        candidates: list[Any] = []
        for path in sorted(runs.glob("*"), reverse=True):
            for name in ("cross_whitelist.json", "whitelist.json"):
                f = path / name
                if f.exists():
                    candidates.append(f)
                    break
            if candidates:
                break
        if not candidates:
            return 0
        import json

        try:
            rows = json.loads(candidates[0].read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(rows, list):
            return 0
        n = self.load_whitelist(rows, replace=True)
        if n:
            self.log(f"очередь восстановлена из {candidates[0].name} · {n}")
        return n

    def to_dict(self) -> dict[str, Any]:
        return {
            "starting_balance": self.starting_balance,
            "order_margin_usdt": self.order_margin_usdt,
            "default_leverage": self.default_leverage,
            "wallet": self.wallet,
            "realized_pnl": self.realized_pnl,
            "running": self.running,
            "bots": {k: asdict(v) for k, v in self.bots.items()},
            "history": [asdict(t) for t in self.history[-100:]],
            "logs": self.logs[-100:],
        }
