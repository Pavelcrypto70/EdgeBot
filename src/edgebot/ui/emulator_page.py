from __future__ import annotations

from typing import Any, Callable

from nicegui import ui

from edgebot.emulator.engine import PaperEmulator

EMU_CSS = """
.emu-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 280px;
  grid-template-rows: minmax(420px, 1fr) 220px;
  gap: 12px;
  min-height: 720px;
}
@media (max-width: 1200px) {
  .emu-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
}
.emu-panel {
  border: 1px solid #243246;
  border-radius: 16px;
  background:
    linear-gradient(180deg, rgba(18,28,43,.92), rgba(10,16,26,.94)),
    repeating-linear-gradient(0deg, transparent, transparent 23px, rgba(46,196,182,.03) 24px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}
.emu-panel::before {
  content: "";
  position: absolute; inset: 8px; pointer-events: none;
  border: 1px solid rgba(46,196,182,.08);
  border-radius: 12px;
}
.emu-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 14px; border-bottom: 1px solid #243246;
  background: rgba(12,18,28,.9);
  z-index: 1;
}
.emu-head h3 {
  margin: 0; font-size: 13px; font-weight: 700; letter-spacing: .04em;
  color: #c9d4e4;
}
.emu-body { padding: 12px 14px; flex: 1; overflow: auto; z-index: 1; }
.emu-left { grid-row: 1 / 3; }
.emu-pos { grid-column: 2; grid-row: 1; }
.emu-bal { grid-column: 3; grid-row: 1; }
.emu-logs { grid-column: 2 / 4; grid-row: 2; }
@media (max-width: 1200px) {
  .emu-left, .emu-pos, .emu-bal, .emu-logs { grid-column: 1; grid-row: auto; }
}

.emu-live {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #8fa0b8;
}
.emu-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #54657a; box-shadow: 0 0 0 0 rgba(46,196,182,.4);
}
.emu-dot.on {
  background: #2ec4b6;
  animation: pulse 1.6s ease-out infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(46,196,182,.55); }
  70% { box-shadow: 0 0 0 8px rgba(46,196,182,0); }
  100% { box-shadow: 0 0 0 0 rgba(46,196,182,0); }
}

.emu-equity {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 42px; font-weight: 600; line-height: 1; color: #eef3fa;
  letter-spacing: -0.03em;
}
.emu-equity.up { color: #3ddc97; }
.emu-equity.down { color: #ff6b7a; }
.emu-sub {
  margin-top: 6px; color: #8fa0b8; font-size: 12px;
  font-family: 'IBM Plex Mono', monospace;
}
.emu-stat {
  display: flex; justify-content: space-between; gap: 10px;
  padding: 8px 0; border-bottom: 1px solid #1c2636;
  font-size: 13px;
}
.emu-stat .k { color: #8fa0b8; }
.emu-stat .v { font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
.emu-stat .v.good { color: #3ddc97; }
.emu-stat .v.bad { color: #ff6b7a; }
.emu-stat .v.teal { color: #2ec4b6; }

.pos-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pos-table th {
  text-align: left; color: #8fa0b8; font-weight: 600; font-size: 10px;
  letter-spacing: .04em;
  padding: 8px 8px; border-bottom: 1px solid #243246;
}
.pos-table td {
  padding: 10px 8px; border-bottom: 1px solid #1a2433;
  font-family: 'IBM Plex Mono', monospace; white-space: nowrap;
}
.pos-table tr:hover td { background: rgba(46,196,182,.04); }
.side-long { color: #3ddc97; font-weight: 700; }
.side-short { color: #ff6b7a; font-weight: 700; }
.pnl-cell {
  display: inline-block; min-width: 88px; padding: 4px 8px; border-radius: 8px;
  text-align: right; font-weight: 700;
}
.pnl-cell.good { background: rgba(61,220,151,.14); color: #3ddc97; }
.pnl-cell.bad { background: rgba(255,107,122,.14); color: #ff6b7a; }

.hist-item {
  padding: 8px 0; border-bottom: 1px solid #1a2433;
  font-size: 12px;
}
.hist-item .top {
  display: flex; justify-content: space-between; gap: 8px;
  font-family: 'IBM Plex Mono', monospace;
}
.hist-item .bot { margin-top: 2px; color: #8fa0b8; font-size: 11px; }
.queue-chip {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; margin-bottom: 6px; border-radius: 10px;
  border: 1px solid #243246; background: #0f1826;
  font-size: 12px;
}
.queue-chip .sym { font-weight: 700; }
.queue-chip .meta { color: #8fa0b8; font-family: 'IBM Plex Mono', monospace; font-size: 11px; }

.emu-log {
  font-family: 'IBM Plex Mono', monospace; font-size: 12px; line-height: 1.55;
  color: #b7c6d8; white-space: pre-wrap; margin: 0;
}
.emu-log .hi { color: #2ec4b6; }
.emu-toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
"""


def mount_emulator_page(
    *,
    emu: PaperEmulator,
    get_whitelist_rows: Callable[[], list[dict[str, Any]]],
    on_tick_async: Callable[[], Any],
) -> dict[str, Any]:
    """Экран эмулятора: позиции / баланс / логи / отчёт."""
    ui.add_head_html(f"<style>{EMU_CSS}</style>")

    live_dot = None
    live_lbl = None
    equity_lbl = None
    equity_sub = None
    stat_labels: dict[str, Any] = {}
    hist_box = None
    queue_box = None
    pos_box = None
    log_box = None

    with ui.element("div").classes("emu-shell"):
        with ui.element("div").classes("emu-panel emu-left"):
            with ui.element("div").classes("emu-head"):
                ui.html("<h3>Отчёт</h3>")
                with ui.element("div").classes("emu-live"):
                    live_dot = ui.element("span").classes("emu-dot")
                    live_lbl = ui.label("ожидание")
            with ui.element("div").classes("emu-body"):
                with ui.element("div").classes("emu-toolbar"):
                    ui.button("Старт эфира", on_click=lambda: _start()).props(
                        "unelevated color=teal text-color=black no-caps dense"
                    )
                    ui.button("Стоп", on_click=lambda: _stop()).props(
                        "outline color=negative no-caps dense"
                    )
                    ui.button("Из whitelist", on_click=lambda: _sync_wl()).props(
                        "outline color=amber no-caps dense"
                    )
                    ui.button("Сброс счёта", on_click=lambda: _reset()).props(
                        "flat color=grey no-caps dense"
                    )
                ui.html(
                    '<div style="color:#8fa0b8;font-size:12px;margin-bottom:10px">'
                    f"Баланс {emu.starting_balance:.0f} USDT · маржа {emu.order_margin_usdt:.0f}$ ×"
                    f"{int(emu.default_leverage)} = "
                    f"{emu.order_margin_usdt * emu.default_leverage:.0f}$ в позиции. "
                    "Очередь из whitelist.</div>"
                )
                ui.html(
                    '<div style="font-size:11px;color:#8fa0b8;margin:8px 0 6px">Очередь</div>'
                )
                queue_box = ui.element("div")
                ui.html(
                    '<div style="font-size:11px;color:#8fa0b8;margin:14px 0 6px">История</div>'
                )
                hist_box = ui.element("div")

        with ui.element("div").classes("emu-panel emu-pos"):
            with ui.element("div").classes("emu-head"):
                ui.html("<h3>Открытые позиции</h3>")
                pos_count = ui.label("0").classes("status")
            pos_box = ui.element("div").classes("emu-body")

        with ui.element("div").classes("emu-panel emu-bal"):
            with ui.element("div").classes("emu-head"):
                ui.html("<h3>Баланс</h3>")
            with ui.element("div").classes("emu-body"):
                equity_lbl = ui.label("0.00 USDT").classes("emu-equity")
                equity_sub = ui.label("бумажный счёт").classes("emu-sub")
                for key, lab in [
                    ("wallet", "Кошелёк"),
                    ("available", "Свободно"),
                    ("in_pos", "В позициях"),
                    ("unreal", "Плавающий PnL"),
                    ("real", "Зафиксированный PnL"),
                    ("wr", "Винрейт"),
                    ("closed", "Закрыто сделок"),
                    ("queue", "В очереди"),
                    ("order", "Маржа ордера"),
                    ("notional", "В позиции"),
                    ("lev", "Плечо"),
                ]:
                    with ui.element("div").classes("emu-stat"):
                        ui.html(f'<span class="k">{lab}</span>')
                        stat_labels[key] = ui.label("—").classes("v")

        with ui.element("div").classes("emu-panel emu-logs"):
            with ui.element("div").classes("emu-head"):
                ui.html("<h3>Логи · исполнение</h3>")
                tick_lbl = ui.label("тик 0").classes("status")
            with ui.element("div").classes("emu-body").style("max-height:180px"):
                log_box = ui.html('<pre class="emu-log">ждём трейдера…</pre>')

    def _start() -> None:
        if not emu.bots:
            _sync_wl()
        emu.start()
        ui.notify("Эмулятор в эфире", type="positive")
        refresh()

    def _stop() -> None:
        emu.stop()
        ui.notify("Эмулятор остановлен", type="warning")
        refresh()

    def _sync_wl() -> None:
        rows = get_whitelist_rows()
        n = emu.load_whitelist(rows, replace=True)
        ui.notify(f"В очередь: {n}", type="info" if n else "warning")
        refresh()

    def _reset() -> None:
        emu.reset_account()
        refresh()

    def refresh(snap: dict[str, Any] | None = None) -> None:
        s = snap or emu.snapshot()
        if s["running"]:
            live_dot.classes(add="on", remove="")
            live_lbl.set_text("в эфире")
        else:
            live_dot.classes(remove="on")
            live_lbl.set_text("ожидание")

        eq = float(s["equity"])
        start = float(emu.starting_balance)
        equity_lbl.set_text(f"{eq:,.2f} USDT")
        equity_lbl.classes(remove="up down")
        if eq > start:
            equity_lbl.classes(add="up")
        elif eq < start:
            equity_lbl.classes(add="down")
        u = float(s["unrealized"])
        equity_sub.set_text(
            f"старт {start:.0f} · откр. PnL {u:+.2f} · тиков {s['ticks']} · открыто {s['open_n']}"
        )

        def _set(key: str, text: str, cls: str | None = None) -> None:
            lab = stat_labels[key]
            lab.set_text(text)
            lab.classes(remove="good bad teal")
            if cls:
                lab.classes(add=cls)

        _set("wallet", f"{s['wallet']:,.2f} USDT")
        _set("available", f"{s['available']:,.2f} USDT", "teal")
        _set("in_pos", f"{s['in_positions']:,.2f} USDT")
        _set("unreal", f"{u:+.2f} USDT", "good" if u >= 0 else "bad")
        r = float(s["realized"])
        _set("real", f"{r:+.2f} USDT", "good" if r >= 0 else "bad")
        _set("wr", f"{s['winrate']:.0f}%", "good" if s["winrate"] >= 55 else None)
        _set("closed", str(s["closed_n"]))
        _set("queue", str(s["queue_n"]), "teal")
        _set(
            "order",
            f"{s.get('order_margin', emu.order_margin_usdt):.0f} USDT",
            "teal",
        )
        _set(
            "notional",
            f"{s.get('order_notional', emu.order_margin_usdt * emu.default_leverage):.0f} USDT",
            "teal",
        )
        _set("lev", f"x{int(s.get('leverage', emu.default_leverage))}")
        pos_count.set_text(str(s["open_n"]))
        tick_lbl.set_text(f"тик {s['ticks']}")

        queue_box.clear()
        with queue_box:
            if not s["queue"]:
                ui.html(
                    '<div class="empty" style="padding:16px"><strong>Пусто</strong>'
                    "Сначала Proof / Кресты</div>"
                )
            else:
                for q in s["queue"]:
                    mark = "●" if q["open"] else "○"
                    ui.html(
                        f'<div class="queue-chip"><div><div class="sym">{mark} {q["symbol"]}</div>'
                        f'<div class="meta">{q["strategy"]} · {q["ma"]} · '
                        f'proof {q["wr"]:.0f}%</div></div></div>'
                    )

        hist_box.clear()
        with hist_box:
            if not s["history"]:
                ui.html(
                    '<div style="color:#8fa0b8;font-size:12px;padding:8px 0">'
                    "Пока нет закрытых</div>"
                )
            else:
                for h in s["history"][:12]:
                    color = "#3ddc97" if h["win"] else "#ff6b7a"
                    ui.html(
                        f'<div class="hist-item"><div class="top">'
                        f'<span>{h["symbol"]} {h["side"]}</span>'
                        f'<span style="color:{color}">{h["pnl"]:+.2f}</span></div>'
                        f'<div class="bot">{h["reason"]} · {h["when"]}</div></div>'
                    )

        pos_box.clear()
        with pos_box:
            rows = s["positions"]
            if not rows:
                ui.html(
                    '<div class="empty"><strong>Нет открытых</strong>'
                    "Ждём сигнал по монетам из whitelist</div>"
                )
            else:
                cells = []
                for p in rows:
                    cls = "good" if p["pnl"] >= 0 else "bad"
                    side_cls = (
                        "side-long" if p.get("side_raw") == "long" else "side-short"
                    )
                    cells.append(
                        "<tr>"
                        f"<td><b>{p['symbol']}</b></td>"
                        f"<td class='{side_cls}'>{p['side']}</td>"
                        f"<td>{p['size']}</td>"
                        f"<td>{p['value']:,.2f}$</td>"
                        f"<td>{p['entry']:.6g}</td>"
                        f"<td>{p['mark']:.6g}</td>"
                        f"<td><span class='pnl-cell {cls}'>{p['pnl']:+.2f}</span></td>"
                        f"<td>{p['lev']}</td>"
                        f"<td>{p['margin']:.2f}</td>"
                        "</tr>"
                    )
                ui.html(
                    "<table class='pos-table'><thead><tr>"
                    "<th>Монета</th><th>Сторона</th><th>Размер</th><th>Объём</th>"
                    "<th>Вход</th><th>Марка</th><th>PnL</th><th>Плечо</th><th>Маржа</th>"
                    "</tr></thead><tbody>"
                    + "".join(cells)
                    + "</tbody></table>"
                )

        log_lines = s["logs"][-60:] or ["ждём трейдера…"]
        pretty = []
        for line in log_lines:
            if "ОТКРЫТИЕ" in line or "В ЭФИРЕ" in line or "эфире" in line:
                pretty.append(f'<span class="hi">{line}</span>')
            else:
                pretty.append(line)
        log_box.set_content('<pre class="emu-log">' + "\n".join(pretty) + "</pre>")

    refresh()
    return {"refresh": refresh, "emu": emu, "on_tick_async": on_tick_async}
