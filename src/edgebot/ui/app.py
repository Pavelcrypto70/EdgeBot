from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import plotly.graph_objects as go
from nicegui import ui

from edgebot.analytics.universe import screen_tickers
from edgebot.bybit.client import BybitClient
from edgebot.config import load_config
from edgebot.emulator.engine import PaperEmulator
from edgebot.research.pipeline import run_proof_research
from edgebot.research.pipeline_cross import run_cross_heavy_research
from edgebot.ui.emulator_page import mount_emulator_page

# Отдельные пулы: proof долгий, скринер должен отвечать сразу
_SCREEN_EXEC = ThreadPoolExecutor(max_workers=2, thread_name_prefix="screen")
_PROOF_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="proof")
_EMU_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="emu")
_EMU = PaperEmulator(
    starting_balance=1000.0,
    order_margin_usdt=100.0,
    default_leverage=3.0,
)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Outfit:wght@500;600;700;800&display=swap');

:root {
  --bg0: #070b12;
  --bg1: #0d141f;
  --bg2: #121c2b;
  --line: #243246;
  --text: #eef3fa;
  --muted: #8fa0b8;
  --teal: #2ec4b6;
  --gold: #f0b429;
  --good: #3ddc97;
  --bad: #ff6b7a;
}

html, body, .q-page { background: var(--bg0) !important; }
body {
  margin: 0;
  color: var(--text);
  font-family: Outfit, system-ui, sans-serif;
  background:
    radial-gradient(900px 420px at 0% -10%, rgba(46,196,182,.16), transparent 55%),
    radial-gradient(700px 380px at 100% 0%, rgba(240,180,41,.08), transparent 50%),
    linear-gradient(180deg, #0a101a 0%, var(--bg0) 40%) !important;
}

.shell { max-width: 1560px; margin: 0 auto; padding: 18px 18px 40px; }

.hero {
  display: grid; grid-template-columns: 1.4fr auto; gap: 16px; align-items: end;
  margin-bottom: 16px;
}
.logo { font-size: 34px; font-weight: 800; letter-spacing: -0.04em; line-height: 1; }
.logo em { font-style: normal; color: var(--teal); }
.tag {
  margin-top: 8px; color: var(--muted); font-size: 14px; max-width: 620px; line-height: 1.35;
}
.actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }

.controls {
  display: grid; grid-template-columns: repeat(5, minmax(0,1fr)); gap: 10px;
  padding: 12px; border: 1px solid var(--line); border-radius: 16px;
  background: rgba(13,20,31,.85); margin-bottom: 14px;
}

.kpis { display: grid; grid-template-columns: repeat(5, minmax(0,1fr)); gap: 10px; margin-bottom: 14px; }
.kpi {
  border: 1px solid var(--line); border-radius: 16px; padding: 14px 14px 12px;
  background: linear-gradient(165deg, rgba(18,28,43,.95), rgba(10,16,26,.9));
}
.kpi .l { font-size: 11px; color: var(--muted); letter-spacing: .08em; text-transform: uppercase; }
.kpi .n { margin-top: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 24px; font-weight: 600; }
.kpi .n.teal { color: var(--teal); }
.kpi .n.gold { color: var(--gold); }
.kpi .n.good { color: var(--good); }

.layout {
  display: grid; grid-template-columns: 320px 1fr; gap: 14px; min-height: 720px;
}
@media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } }

.side, .main {
  border: 1px solid var(--line); border-radius: 18px;
  background: rgba(13,20,31,.9); overflow: hidden;
}
.side-head, .main-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 14px; border-bottom: 1px solid var(--line);
  background: rgba(18,28,43,.9);
}
.side-head h3, .main-head h3 { margin: 0; font-size: 15px; font-weight: 700; }
.side-list { max-height: 760px; overflow: auto; padding: 10px; display: flex; flex-direction: column; gap: 8px; }

.card {
  display: block; text-align: left; width: 100%; cursor: pointer;
  border: 1px solid var(--line); border-radius: 14px; padding: 12px;
  background: #0f1826; color: var(--text); font: inherit;
  transition: border-color .15s, transform .15s, background .15s;
}
.card:hover { border-color: rgba(46,196,182,.55); transform: translateY(-1px); }
.card.active { border-color: var(--teal); background: rgba(46,196,182,.08); }
.card .sym { font-size: 16px; font-weight: 700; }
.card .meta { margin-top: 4px; color: var(--muted); font-size: 12px; font-family: 'IBM Plex Mono', monospace; }
.badge {
  display: inline-block; margin-top: 8px; padding: 3px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 700; letter-spacing: .04em;
}
.badge.wl { background: rgba(61,220,151,.15); color: var(--good); }
.badge.rej { background: rgba(255,107,122,.12); color: var(--bad); }
.badge.fast { background: rgba(240,180,41,.14); color: var(--gold); margin-left: 6px; }
.badge.heavy { background: rgba(46,196,182,.14); color: var(--teal); margin-left: 6px; }

.main-body { padding: 12px 14px 18px; }
.metric-strip {
  display: grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap: 8px; margin-bottom: 12px;
}
.m {
  border: 1px solid var(--line); border-radius: 12px; padding: 10px;
  background: #0c1420;
}
.m .l { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.m .v { margin-top: 4px; font-family: 'IBM Plex Mono', monospace; font-size: 16px; font-weight: 600; }
.proof-card {
  margin: 0 0 14px; padding: 16px 18px; border-radius: 16px; line-height: 1.45;
}
.proof-card.ok {
  border: 1px solid rgba(61,220,151,.35); background: rgba(61,220,151,.08);
}
.proof-card.bad {
  border: 1px solid rgba(255,107,122,.35); background: rgba(255,107,122,.08);
}
.proof-title {
  font-size: 18px; font-weight: 800; margin-bottom: 8px; color: #eef3fa;
}
.proof-card.ok .proof-title { color: #3ddc97; }
.proof-card.bad .proof-title { color: #ff8a96; }
.proof-summary { color: #d5deea; font-size: 14px; margin-bottom: 10px; }
.proof-list { margin: 0 0 10px 18px; padding: 0; color: #c7d5e6; font-size: 13.5px; }
.proof-list li { margin: 0 0 6px; }
.proof-mini {
  font-size: 12px; color: #8fa0b8; border-top: 1px solid #243246; padding-top: 10px;
}
.empty {
  padding: 48px 20px; text-align: center; color: var(--muted);
}
.empty strong { display:block; color: var(--text); font-size: 18px; margin-bottom: 8px; }

.q-btn { font-weight: 700 !important; border-radius: 12px !important; }
.status { color: var(--muted); font-size: 12px; font-family: 'IBM Plex Mono', monospace; }

.nav-row {
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  margin-bottom: 14px;
}
.nav {
  display: flex; gap: 8px; padding: 6px;
  border: 1px solid var(--line); border-radius: 14px;
  background: rgba(13,20,31,.75); width: fit-content;
}
.nav-btn {
  border: 0; background: transparent; color: var(--muted);
  font: inherit; font-weight: 700; font-size: 13px;
  padding: 8px 14px; border-radius: 10px; cursor: pointer;
}
.nav-btn.active {
  background: rgba(46,196,182,.16); color: var(--teal);
}
.go-btn {
  font-size: 15px !important;
  padding: 10px 22px !important;
  letter-spacing: 0.02em;
  box-shadow: 0 0 0 1px rgba(46,196,182,.35), 0 8px 28px rgba(46,196,182,.18) !important;
}
"""


def _empty_fig(title: str) -> dict:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="#0b1017",
        plot_bgcolor="#101722",
        font=dict(color="#8fa0b8"),
        title=title,
        height=360,
        margin=dict(l=30, r=20, t=40, b=30),
    )
    fig.add_annotation(
        text="Запусти Proof MA → Whitelist",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="#8fa0b8"),
    )
    return fig.to_plotly_json()


def _safe_rows(df_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in df_records:
        item: dict[str, Any] = {}
        for k, v in r.items():
            if v is None:
                item[k] = None
            elif hasattr(v, "item"):
                item[k] = v.item()
            elif isinstance(v, (bool, int, float, str)):
                item[k] = v
            else:
                item[k] = str(v)
            if k == "whitelist":
                item[k] = bool(v)
        out.append(item)
    return out


# keep proof_html as raw HTML string (already safe from our generator)


def build_ui() -> None:
    ui.add_head_html(f"<style>{CSS}</style>")

    state: dict[str, Any] = {
        "busy_screen": False,
        "busy_proof": False,
        "busy_emu": False,
        "page": "research",
        "status": "idle",
        "universe_n": 0,
        "proof_n": 0,
        "wl_n": 0,
        "emu_n": 0,
        "results": [],
        "screen_rows": [],
        "artifacts": {},
        "selected": None,
        "side_mode": "proof",  # proof | screen
    }
    emu_api: dict[str, Any] = {}

    with ui.element("div").classes("shell"):
        with ui.element("div").classes("hero"):
            with ui.element("div"):
                ui.html('<div class="logo">EDGE<em>BOT</em></div>')
                tag_lbl = ui.html(
                    '<div class="tag">Смотрим историю сделок по скользящим. Слева на графике — обучение, '
                    "справа от пунктира — проверка. В whitelist только если на проверке реально плюс.</div>"
                )
            actions = ui.element("div").classes("actions")

        with ui.element("div").classes("nav-row"):
            with ui.element("div").classes("nav"):
                nav_research = ui.button("Исследование", on_click=lambda: show_page("research")).props(
                    "flat no-caps"
                ).classes("nav-btn active")
                nav_emu = ui.button("Эмулятор", on_click=lambda: show_page("emulator")).props(
                    "flat no-caps"
                ).classes("nav-btn")
            btn_go = ui.button("▶  ЗАПУСК").props(
                "unelevated color=teal text-color=black no-caps"
            ).classes("go-btn")

        page_research = ui.element("div")
        page_emulator = ui.element("div")
        page_emulator.set_visibility(False)

        with page_research:
            with ui.element("div").classes("controls"):
                cat = ui.select(
                    {"linear": "linear", "all": "all", "spot": "spot"},
                    value="linear",
                    label="Рынок",
                )
                heavy_n = ui.number("Heavy", value=8, min=4, max=15)
                fast_n = ui.number("Fast Δ", value=10, min=4, max=20)
                min_turn = ui.number("Мин. оборот млн", value=2.0, min=0.5, max=50, step=0.5)
                status_lbl = ui.label("idle").classes("status").style("align-self:center")

            with ui.element("div").classes("kpis"):
                with ui.element("div").classes("kpi"):
                    ui.html('<div class="l">Universe</div>')
                    k_uni = ui.label("0").classes("n teal")
                with ui.element("div").classes("kpi"):
                    ui.html('<div class="l">Researched</div>')
                    k_res = ui.label("0").classes("n")
                with ui.element("div").classes("kpi"):
                    ui.html('<div class="l">Whitelist</div>')
                    k_wl = ui.label("0").classes("n good")
                with ui.element("div").classes("kpi"):
                    ui.html('<div class="l">Emulator</div>')
                    k_emu = ui.label("0").classes("n gold")
                with ui.element("div").classes("kpi"):
                    ui.html('<div class="l">Selected</div>')
                    k_sel = ui.label("—").classes("n teal")

            with ui.element("div").classes("layout"):
                with ui.element("div").classes("side"):
                    with ui.element("div").classes("side-head"):
                        ui.html("<h3>Кандидаты</h3>")
                        side_hint = ui.label("после proof").classes("status")
                    side_list = ui.element("div").classes("side-list")
                    with side_list:
                        ui.html(
                            '<div class="empty"><strong>Пока пусто</strong>'
                            "Нажми Proof MA → Whitelist</div>"
                        )

                with ui.element("div").classes("main"):
                    with ui.element("div").classes("main-head"):
                        main_title = ui.label("Proof view").style("font-weight:700;font-size:15px")
                        main_sub = ui.label("выбери монету слева").classes("status")
                    with ui.element("div").classes("main-body"):
                        with ui.element("div").classes("metric-strip"):
                            m_labels = {}
                            for key, lab in [
                                ("wr", "Винрейт"),
                                ("verdict", "Whitelist"),
                                ("ma", "Средние"),
                                ("n", "Сделок"),
                                ("oos_wr", "Свежий %"),
                                ("exp", "Ср. результат"),
                            ]:
                                with ui.element("div").classes("m"):
                                    ui.html(f'<div class="l">{lab}</div>')
                                    m_labels[key] = ui.label("—").classes("v")
                        proof_text = ui.html(
                            '<div class="proof-card"><div class="proof-title">Выбери монету слева</div>'
                            '<div class="proof-summary">После Proof здесь будет понятный вердикт: брать или нет.</div></div>'
                        )
                        chart_price = ui.plotly(
                            _empty_fig("Цена и скользящие · треугольники = входы")
                        ).classes("w-full")
                        chart_eq = ui.plotly(
                            _empty_fig("Накопительный результат сделок (жёлтое = проверка)")
                        ).classes("w-full")

        def show_page(name: str) -> None:
            state["page"] = name
            page_research.set_visibility(name == "research")
            page_emulator.set_visibility(name == "emulator")
            nav_research.classes(remove="active")
            nav_emu.classes(remove="active")
            if name == "research":
                nav_research.classes(add="active")
                tag_lbl.set_content(
                    '<div class="tag">Смотрим историю сделок по скользящим. Слева — обучение, '
                    "справа от пунктира — проверка. В whitelist только если на проверке плюс.</div>"
                )
                actions.set_visibility(True)
            else:
                nav_emu.classes(add="active")
                tag_lbl.set_content(
                    '<div class="tag">Бумажный эмулятор: баланс 1000 USDT, ордер 100$ маржи ×3 = 300$ в позиции. '
                    "Открытые позиции, баланс, логи и короткая история.</div>"
                )
                actions.set_visibility(False)
                if emu_api.get("refresh"):
                    emu_api["refresh"]()

        def whitelist_rows() -> list[dict[str, Any]]:
            return [r for r in (state["results"] or []) if r.get("whitelist")]

        async def emu_tick_job() -> None:
            if not _EMU.running or state["busy_emu"]:
                return
            state["busy_emu"] = True
            loop = asyncio.get_running_loop()
            try:
                cfg = load_config()

                def job():
                    with BybitClient(timeout=12.0) as client:
                        return _EMU.tick(client, cfg=cfg)

                snap = await loop.run_in_executor(_EMU_EXEC, job)
                if state["page"] == "emulator" and emu_api.get("refresh"):
                    emu_api["refresh"](snap)
                state["emu_n"] = int(snap.get("queue_n") or 0)
                k_emu.set_text(str(state["emu_n"]))
            except Exception as exc:  # noqa: BLE001
                _EMU.log(f"ошибка тика: {exc}")
                if emu_api.get("refresh"):
                    emu_api["refresh"]()
            finally:
                state["busy_emu"] = False

        with page_emulator:
            if not _EMU.bots:
                restored = _EMU.load_latest_run_whitelist()
                if restored:
                    state["emu_n"] = restored
                    # очередь с диска есть — сразу включаем эфир, иначе «ожидание» и 0 тиков
                    _EMU.start()
            emu_api.update(
                mount_emulator_page(
                    emu=_EMU,
                    get_whitelist_rows=whitelist_rows,
                    on_tick_async=emu_tick_job,
                )
            )

        ui.timer(12.0, emu_tick_job)

    def set_kpis() -> None:
        k_uni.set_text(str(state["universe_n"]))
        k_res.set_text(str(state["proof_n"]))
        k_wl.set_text(str(state["wl_n"]))
        k_emu.set_text(str(state["emu_n"]))
        k_sel.set_text(state["selected"] or "—")
        status_lbl.set_text(state["status"])

    def show_symbol(symbol: str) -> None:
        state["selected"] = symbol
        state["side_mode"] = "proof"
        art = state["artifacts"].get(symbol) or {}
        row = next((r for r in state["results"] if str(r.get("symbol")) == symbol), None)
        set_kpis()
        render_side()
        main_title.set_text(f"{symbol}")
        if not row:
            main_sub.set_text("нет результата")
            return
        bucket_ru = "тяжёлая" if row.get("bucket") == "heavy" else "быстрая"
        wr_pct = float(row.get("winrate_pct") or 0)
        main_sub.set_text(f"{bucket_ru} · винрейт {wr_pct:.0f}%")
        m_labels["wr"].set_text(f"{wr_pct:.0f}%")
        m_labels["verdict"].set_text("ДА" if row.get("whitelist") else "нет")
        m_labels["ma"].set_text(f"{row.get('ema_fast')} / {row.get('ema_slow')}")
        m_labels["n"].set_text(str(row.get("trades_n") or row.get("oos_n") or "—"))
        oos_wr = row.get("oos_wr")
        m_labels["oos_wr"].set_text(
            f"{float(oos_wr) * 100:.0f}%" if oos_wr is not None else "—"
        )
        exp = float(row.get("oos_exp_r") or row.get("train_exp_r") or 0)
        m_labels["exp"].set_text(f"{exp:+.2f}")
        html = row.get("proof_html")
        if html:
            proof_text.set_content(str(html))
        else:
            # fallback for old runs
            proof_text.set_content(
                f'<div class="proof-card bad"><div class="proof-title">{row.get("verdict")}</div>'
                f'<div class="proof-summary">{row.get("proof")}</div></div>'
            )
        figs = art.get("figures") or {}
        try:
            if "price" in figs:
                chart_price.update_figure(figs["price"])
            if "equity" in figs:
                chart_eq.update_figure(figs["equity"])
        except Exception as exc:  # noqa: BLE001
            ui.notify(f"График: {exc}", type="warning")

    def render_side() -> None:
        side_list.clear()
        if state["side_mode"] == "screen":
            rows = list(state["screen_rows"] or [])
            if not rows:
                with side_list:
                    ui.html(
                        '<div class="empty"><strong>Скринер пуст</strong>Нажми «Скринер» ещё раз</div>'
                    )
                side_hint.set_text("0")
                return
            side_hint.set_text(f"скринер · {len(rows)}")
            with side_list:
                for r in rows:
                    sym = str(r.get("symbol"))
                    ui.html(
                        f'<div class="card" style="cursor:default">'
                        f'<div class="sym">{sym}</div>'
                        f'<div class="meta">{r.get("category")} · оборот {r.get("turnover")} · '
                        f'24ч {r.get("chg")}%</div></div>'
                    )
            return

        rows = list(state["results"] or [])
        if not rows:
            with side_list:
                ui.html(
                    '<div class="empty"><strong>Пока пусто</strong>Нажми Proof MA → Whitelist</div>'
                )
            side_hint.set_text("0 шт")
            return
        rows = sorted(
            rows,
            key=lambda r: (
                not bool(r.get("whitelist")),
                -float(r.get("winrate_pct") or 0),
            ),
        )
        side_hint.set_text(f"{len(rows)} шт · WL {sum(1 for r in rows if r.get('whitelist'))}")
        with side_list:
            for r in rows:
                sym = str(r.get("symbol"))
                active = "active" if sym == state["selected"] else ""
                badge = "wl" if r.get("whitelist") else "rej"
                bucket = "heavy" if r.get("bucket") == "heavy" else "fast"
                wr = float(r.get("winrate_pct") or 0)
                card = ui.element("button").classes(f"card {active}")
                card.on("click", lambda _e=None, s=sym: show_symbol(s))
                with card:
                    ui.html(
                        f'<div class="sym">{sym} · <span style="color:#2ec4b6">{wr:.0f}%</span></div>'
                        f'<div class="meta">средние {r.get("ema_fast")}/{r.get("ema_slow")} · '
                        f'{r.get("trades_n") or r.get("oos_n")} сделок</div>'
                        f'<span class="badge {badge}">{"WL" if r.get("whitelist") else "слабый"}</span>'
                        f'<span class="badge {bucket}">{"тяжёлая" if bucket=="heavy" else "быстрая"}</span>'
                    )

    def sync_buttons() -> None:
        if state["busy_screen"]:
            btn_screen.props("disable")
        else:
            btn_screen.props(remove="disable")
        busy = state["busy_proof"]
        if busy:
            btn_proof.props("disable")
            btn_cross.props("disable")
            btn_go.props("disable")
        else:
            btn_proof.props(remove="disable")
            btn_cross.props(remove="disable")
            btn_go.props(remove="disable")

    def cfg_ui():
        cfg = load_config()
        cfg.universe.min_turnover_usdt = float(min_turn.value or 2) * 1_000_000
        if cat.value == "linear":
            cfg.universe.categories = ["linear"]
        elif cat.value == "spot":
            cfg.universe.categories = ["spot"]
        return cfg

    async def do_screen() -> None:
        if state["busy_screen"]:
            return
        state["busy_screen"] = True
        sync_buttons()
        state["status"] = "скринер…"
        state["side_mode"] = "screen"
        set_kpis()
        ui.notify("Обновляю скринер…", type="info")
        cfg = cfg_ui()
        loop = asyncio.get_running_loop()

        def job():
            with BybitClient(timeout=12.0) as client:
                return screen_tickers(client, cfg)

        try:
            df = await asyncio.wait_for(
                loop.run_in_executor(_SCREEN_EXEC, job),
                timeout=25.0,
            )
            rows = []
            for i, r in enumerate(df.head(40).itertuples(index=False), start=1):
                d = r._asdict()
                turn = float(d.get("turnover_24h") or 0)
                rows.append(
                    {
                        "rank": i,
                        "symbol": str(d.get("symbol")),
                        "category": str(d.get("category")),
                        "turnover": f"{turn/1e6:.1f}M",
                        "chg": round(float(d.get("price_change_pct_24h") or 0), 2),
                    }
                )
            state["screen_rows"] = rows
            state["universe_n"] = len(df)
            state["status"] = f"скринер {len(df)}"
            set_kpis()
            render_side()
            ui.notify(f"Скринер: {len(df)} рынков", type="positive")
        except TimeoutError:
            state["status"] = "скринер: таймаут"
            set_kpis()
            ui.notify("Bybit не ответил за 25 сек — попробуй ещё раз", type="warning")
        except Exception as exc:  # noqa: BLE001
            state["status"] = str(exc)[:60]
            set_kpis()
            ui.notify(str(exc), type="negative")
        finally:
            state["busy_screen"] = False
            sync_buttons()

    def apply_bundle(bundle, *, label: str) -> None:
        state["universe_n"] = len(bundle.universe)
        state["proof_n"] = len(bundle.results)
        state["wl_n"] = len(bundle.whitelist)
        state["emu_n"] = len(bundle.emulator_queue)
        state["results"] = (
            _safe_rows(bundle.results.to_dict(orient="records"))
            if not bundle.results.empty
            else []
        )
        state["artifacts"] = {
            sym: {
                "symbol": art.get("symbol"),
                "bucket": art.get("bucket"),
                "params": art.get("params"),
                "proof": art.get("proof"),
                "figures": art.get("figures") or {},
            }
            for sym, art in (bundle.artifacts or {}).items()
        }
        state["side_mode"] = "proof"
        state["status"] = f"{label} · WL {state['wl_n']}"
        # Автозагрузка прошедших в эмулятор + старт LIVE
        wl_rows = [r for r in state["results"] if r.get("whitelist")]
        n = _EMU.load_whitelist(wl_rows, replace=True)
        state["emu_n"] = n
        if n:
            if not _EMU.running:
                _EMU.start()
            _EMU.log(f"очередь из «{label}» · {n} монет · в эфире")
        set_kpis()
        render_side()
        if emu_api.get("refresh"):
            emu_api["refresh"]()
        if state["results"]:
            pick = str((wl_rows[0] if wl_rows else state["results"][0])["symbol"])
            show_symbol(pick)

    async def _run_research(job_factory, *, start_msg: str, done_label: str) -> None:
        if state["busy_proof"]:
            return
        state["busy_proof"] = True
        sync_buttons()
        state["status"] = start_msg
        state["side_mode"] = "proof"
        set_kpis()
        ui.notify(start_msg, type="info")
        loop = asyncio.get_running_loop()
        msgs: list[str] = []

        def on_progress(msg: str) -> None:
            msgs.append(msg)

        def job():
            return job_factory(on_progress)

        try:
            task = loop.run_in_executor(_PROOF_EXEC, job)
            while not task.done():
                if msgs:
                    state["status"] = msgs[-1][:48]
                    set_kpis()
                await asyncio.sleep(0.4)
            bundle = await task
            apply_bundle(bundle, label=done_label)
            ui.notify(
                f"{done_label}: WL {state['wl_n']} / {state['proof_n']}",
                type="positive" if state["wl_n"] else "warning",
            )
        except Exception as exc:  # noqa: BLE001
            state["status"] = str(exc)[:60]
            set_kpis()
            ui.notify(str(exc), type="negative")
        finally:
            state["busy_proof"] = False
            sync_buttons()

    async def do_proof() -> None:
        cfg = cfg_ui()

        def factory(on_progress):
            return run_proof_research(
                cfg=cfg,
                max_heavy=int(heavy_n.value or 8),
                max_fast=int(fast_n.value or 10),
                quiet=True,
                on_progress=on_progress,
            )

        await _run_research(factory, start_msg="Proof MA…", done_label="Proof MA")

    async def do_crosses() -> None:
        cfg = cfg_ui()

        def factory(on_progress):
            return run_cross_heavy_research(
                cfg=cfg,
                max_heavy=int(heavy_n.value or 12),
                quiet=True,
                on_progress=on_progress,
            )

        await _run_research(factory, start_msg="Кресты heavy…", done_label="Кресты")

    async def do_full_go() -> None:
        """Вся цепочка: Proof → whitelist → эфир. Если очередь уже есть — сразу в эфир."""
        if state["busy_proof"]:
            return

        # Уже есть очередь (как на скрине) — не гоняем proof заново, сразу эфир
        if not _EMU.bots:
            _EMU.load_latest_run_whitelist()
        wl_now = [r for r in (state["results"] or []) if r.get("whitelist")]
        if wl_now and not _EMU.bots:
            _EMU.load_whitelist(wl_now, replace=True)

        if _EMU.bots:
            if not _EMU.running:
                _EMU.start()
            show_page("emulator")
            ui.notify(
                f"В эфире · {_EMU.snapshot()['queue_n']} монет · 100$×3 = 300$ в позиции",
                type="positive",
            )
            if emu_api.get("refresh"):
                emu_api["refresh"]()
            await emu_tick_job()
            return

        ui.notify("Запуск: проверка → whitelist → эмулятор", type="info")
        show_page("research")
        cfg = cfg_ui()

        def factory(on_progress):
            return run_proof_research(
                cfg=cfg,
                max_heavy=int(heavy_n.value or 8),
                max_fast=int(fast_n.value or 10),
                quiet=True,
                on_progress=on_progress,
            )

        await _run_research(factory, start_msg="ЗАПУСК · Proof…", done_label="ЗАПУСК")
        wl = [r for r in (state["results"] or []) if r.get("whitelist")]
        if not wl:
            def factory_cross(on_progress):
                return run_cross_heavy_research(
                    cfg=cfg,
                    max_heavy=int(heavy_n.value or 12),
                    quiet=True,
                    on_progress=on_progress,
                )

            await _run_research(
                factory_cross, start_msg="ЗАПУСК · кресты…", done_label="ЗАПУСК кресты"
            )

        if not _EMU.bots:
            _EMU.load_latest_run_whitelist()

        if _EMU.bots:
            if not _EMU.running:
                _EMU.start()
            show_page("emulator")
            ui.notify(
                f"В эфире · {_EMU.snapshot()['queue_n']} в очереди · 100$×3 = 300$",
                type="positive",
            )
            await emu_tick_job()
        else:
            ui.notify("Whitelist пуст — эмулятор не стартовал", type="warning")

    btn_go.on_click(do_full_go)

    with actions:
        btn_screen = ui.button("Скринер", on_click=do_screen).props("outline color=teal no-caps")
        btn_proof = ui.button("Proof MA → Whitelist", on_click=do_proof).props(
            "outline color=teal no-caps"
        )
        btn_cross = ui.button("Кресты (тяжёлые)", on_click=do_crosses).props(
            "outline color=amber no-caps"
        )


def run_ui() -> None:
    ui.run(
        root=build_ui,
        title="EdgeBot Desk",
        host="127.0.0.1",
        port=43123,
        reload=False,
        show=True,
        dark=True,
    )
