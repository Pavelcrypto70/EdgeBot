from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from edgebot.analytics.indicators import enrich
from edgebot.backtest.engine import split_train_oos
from edgebot.strategies.ema_ma import StrategyParams


CHART_LAYOUT = dict(
    paper_bgcolor="#0b1017",
    plot_bgcolor="#101722",
    font=dict(family="IBM Plex Mono, Outfit, sans-serif", color="#c9d4e4", size=12),
    margin=dict(l=48, r=24, t=40, b=36),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    xaxis=dict(gridcolor="#1c2636", zeroline=False),
    yaxis=dict(gridcolor="#1c2636", zeroline=False),
    hovermode="x unified",
)


def _x_axis(frame: pd.DataFrame) -> list[str]:
    if "ts" not in frame.columns:
        return [str(i) for i in range(len(frame))]
    ts = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
    return [t.isoformat() if pd.notna(t) else "" for t in ts]


def build_proof_figures(
    entry: pd.DataFrame,
    trades: pd.DataFrame,
    params: StrategyParams,
    *,
    symbol: str,
    oos_frac: float = 0.3,
) -> dict[str, dict[str, Any]]:
    """Return Plotly figures as JSON-safe dicts (no pandas Timestamp)."""
    e = enrich(entry, ema_fast=params.ema_fast, ema_slow=params.ema_slow).reset_index(drop=True)
    cut, _ = split_train_oos(len(e), oos_frac)
    x = _x_axis(e)

    price = go.Figure()
    price.add_trace(
        go.Candlestick(
            x=x,
            open=e["open"].astype(float).tolist(),
            high=e["high"].astype(float).tolist(),
            low=e["low"].astype(float).tolist(),
            close=e["close"].astype(float).tolist(),
            name="OHLC",
            increasing_line_color="#3ddc97",
            decreasing_line_color="#ff6b7a",
            increasing_fillcolor="#3ddc97",
            decreasing_fillcolor="#ff6b7a",
        )
    )
    price.add_trace(
        go.Scatter(
            x=x,
            y=e["ema_fast"].astype(float).tolist(),
            name=f"EMA {params.ema_fast}",
            line=dict(color="#2ec4b6", width=1.6),
        )
    )
    price.add_trace(
        go.Scatter(
            x=x,
            y=e["ema_slow"].astype(float).tolist(),
            name=f"EMA {params.ema_slow}",
            line=dict(color="#f0b429", width=1.8),
        )
    )

    if 0 < cut < len(e):
        price.add_vline(x=x[cut], line_width=1, line_dash="dot", line_color="#8b9bb0")
        price.add_annotation(
            x=x[cut],
            y=1.02,
            yref="paper",
            text="OOS →",
            showarrow=False,
            font=dict(color="#8b9bb0", size=11),
        )

    if trades is not None and not trades.empty:
        for _, t in trades.iterrows():
            ei = int(t["entry_i"])
            xi = int(t["exit_i"])
            if ei >= len(e) or xi >= len(e):
                continue
            win = bool(t.get("win"))
            color = "#3ddc97" if win else "#ff6b7a"
            side = str(t.get("side"))
            marker = "triangle-up" if side == "long" else "triangle-down"
            pnl = float(t["pnl_r"])
            price.add_trace(
                go.Scatter(
                    x=[x[ei]],
                    y=[float(t["entry"])],
                    mode="markers",
                    marker=dict(symbol=marker, size=11, color=color, line=dict(width=1, color="#fff")),
                    name="entry",
                    showlegend=False,
                    hovertemplate=f"{side} entry<br>R={pnl:+.2f}<extra></extra>",
                )
            )
            price.add_trace(
                go.Scatter(
                    x=[x[xi]],
                    y=[float(t["exit"])],
                    mode="markers",
                    marker=dict(symbol="x", size=9, color=color),
                    name="exit",
                    showlegend=False,
                    hovertemplate=f"exit {t.get('reason')}<br>R={pnl:+.2f}<extra></extra>",
                )
            )
            price.add_trace(
                go.Scatter(
                    x=[x[ei], x[xi]],
                    y=[float(t["entry"]), float(t["exit"])],
                    mode="lines",
                    line=dict(color=color, width=1, dash="dot"),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

    price.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=f"{symbol} · MA {params.ema_fast}/{params.ema_slow} · ATR×{params.atr_mult} · TP {params.take_profit_r}R",
            font=dict(size=14, color="#e7eef8"),
        ),
        xaxis_rangeslider_visible=False,
        height=420,
    )

    eq = go.Figure()
    if trades is not None and not trades.empty:
        ordered = trades.sort_values("entry_i").copy()
        ordered["cum_r"] = ordered["pnl_r"].cumsum()
        is_oos = (ordered["entry_i"] >= cut).tolist()
        eq.add_trace(
            go.Scatter(
                x=list(range(1, len(ordered) + 1)),
                y=ordered["cum_r"].astype(float).tolist(),
                mode="lines+markers",
                name="Equity R",
                line=dict(color="#2ec4b6", width=2),
                marker=dict(size=7, color=["#f0b429" if o else "#2ec4b6" for o in is_oos]),
            )
        )
        eq.add_hline(y=0, line_dash="dot", line_color="#2a3648")
    eq.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Кумулятивный R (жёлтые точки = OOS)", font=dict(size=13, color="#e7eef8")),
        height=260,
        yaxis_title="R",
        xaxis_title="сделка #",
    )

    return {"price": price.to_plotly_json(), "equity": eq.to_plotly_json()}


def artifact_from_opt(
    entry: pd.DataFrame,
    opt: dict[str, Any],
    *,
    symbol: str,
    category: str,
    bucket: str,
    proof: dict[str, Any],
) -> dict[str, Any]:
    params_raw = opt.get("params") or {}
    if not params_raw:
        return {}
    params = StrategyParams(**params_raw)
    trades = opt.get("all_trades")
    if trades is None:
        trades = pd.DataFrame()
    # Drop non-JSON ts column from trade records
    trade_records = []
    if isinstance(trades, pd.DataFrame) and not trades.empty:
        clean = trades.copy()
        if "ts" in clean.columns:
            clean["ts"] = pd.to_datetime(clean["ts"], utc=True, errors="coerce").astype(str)
        trade_records = clean.to_dict(orient="records")
    figs = build_proof_figures(entry, trades, params, symbol=symbol)
    cut, _ = split_train_oos(len(entry), 0.3)
    oos_tr = trades[trades["entry_i"] >= cut] if not trades.empty else trades
    oos_records = []
    if isinstance(oos_tr, pd.DataFrame) and not oos_tr.empty:
        c2 = oos_tr.copy()
        if "ts" in c2.columns:
            c2["ts"] = pd.to_datetime(c2["ts"], utc=True, errors="coerce").astype(str)
        oos_records = c2.to_dict(orient="records")
    return {
        "symbol": symbol,
        "category": category,
        "bucket": bucket,
        "params": params_raw,
        "proof": proof,
        "train": opt.get("train"),
        "oos": opt.get("oos"),
        "trades": trade_records,
        "oos_trades": oos_records,
        "figures": figs,
    }
