from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from edgebot.config import AnalyticsConfig, AnalyticsGates, AnalyticsWeights


def _clamp01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def score_liquidity(turnover: float, open_interest: float | None, category: str) -> float:
    # log-ish scale: 2M→low, 50M→strong, 200M+→max
    t = _clamp01(np.log10(max(turnover, 1)) / np.log10(2e8))
    if category == "linear" and open_interest:
        oi = _clamp01(np.log10(max(open_interest, 1)) / np.log10(5e7))
        return 0.7 * t + 0.3 * oi
    return t


def score_microstructure(spread_bps: float | None, max_spread: float) -> float:
    if spread_bps is None or np.isnan(spread_bps):
        return 0.5
    if spread_bps > max_spread:
        return 0.0
    return _clamp01(1.0 - spread_bps / max_spread)


def score_volatility(atr_pct: float, gates: AnalyticsGates) -> float:
    """Sweet spot: enough movement for 1R, not a casino."""
    if atr_pct < gates.min_atr_pct or atr_pct > gates.max_atr_pct:
        return 0.0
    mid = (gates.min_atr_pct + gates.max_atr_pct) / 2
    width = (gates.max_atr_pct - gates.min_atr_pct) / 2
    return _clamp01(1.0 - abs(atr_pct - mid) / max(width, 1e-9))


def score_trend(htf_slope: float, structure: float, aligned: bool, gates: AnalyticsGates) -> float:
    slope_mag = abs(htf_slope)
    if slope_mag < gates.min_htf_slope_abs:
        base = 0.25
    else:
        base = _clamp01(slope_mag / 0.01)
    struct = _clamp01((structure + 1) / 2)
    align_bonus = 0.15 if aligned else 0.0
    return _clamp01(0.55 * base + 0.30 * struct + align_bonus)


def score_momentum(ret_24h: float, ret_7d: float, rsi: float) -> float:
    # Prefer directional but not blow-off tops/bottoms
    dir_24 = _clamp01(abs(ret_24h) / 8.0)
    if abs(ret_24h) > 18:
        dir_24 *= 0.35
    dir_7 = _clamp01(abs(ret_7d) / 20.0)
    if abs(ret_7d) > 45:
        dir_7 *= 0.4
    # RSI away from 50 but not extreme
    rsi_edge = _clamp01(abs(rsi - 50) / 25)
    if rsi < 20 or rsi > 80:
        rsi_edge *= 0.3
    return _clamp01(0.45 * dir_24 + 0.30 * dir_7 + 0.25 * rsi_edge)


def score_relative_strength(symbol_ret: float, btc_ret: float) -> float:
    # Outperformance vs BTC (signed magnitude capped)
    alpha = symbol_ret - btc_ret
    return _clamp01(0.5 + alpha / 20.0)


def score_volume_quality(rvol: float, gates: AnalyticsGates) -> float:
    if rvol < gates.min_rvol:
        return 0.15
    # Peak around 1.5–2.5x, decay after mania
    if rvol <= 2.0:
        return _clamp01((rvol - 0.5) / 1.5)
    if rvol <= 4.0:
        return _clamp01(1.0 - (rvol - 2.0) / 4.0)
    return 0.2


@dataclass(slots=True)
class ScoreResult:
    composite: float
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    parts: dict[str, float] = field(default_factory=dict)


def score_row(
    row: pd.Series,
    feats: dict[str, float],
    *,
    btc_ret_24h: float,
    cfg: AnalyticsConfig,
    max_spread: float,
) -> ScoreResult:
    gates = cfg.gates
    w = cfg.weights
    reasons: list[str] = []

    atr_pct = float(feats.get("atr_pct") or 0.0)
    htf_slope = float(feats.get("htf_slope") or 0.0)
    rvol = float(feats.get("rvol") or 0.0)
    funding = row.get("funding_rate")
    spread = row.get("spread_bps")

    # Hard gates
    if atr_pct < gates.min_atr_pct:
        reasons.append(f"low_atr:{atr_pct:.4f}")
    if atr_pct > gates.max_atr_pct:
        reasons.append(f"high_atr:{atr_pct:.4f}")
    if abs(htf_slope) < gates.min_htf_slope_abs:
        reasons.append(f"flat_htf:{htf_slope:.5f}")
    if rvol < gates.min_rvol:
        reasons.append(f"low_rvol:{rvol:.2f}")
    if (
        row.get("category") == "linear"
        and funding is not None
        and not (isinstance(funding, float) and np.isnan(funding))
        and abs(float(funding)) > gates.max_abs_funding
    ):
        reasons.append(f"funding_extreme:{float(funding):.5f}")
    if spread is not None and not (isinstance(spread, float) and np.isnan(spread)) and float(spread) > max_spread:
        reasons.append(f"wide_spread:{float(spread):.1f}")

    parts = {
        "liquidity": score_liquidity(
            float(row.get("turnover_24h") or 0),
            float(row["open_interest"]) if pd.notna(row.get("open_interest")) else None,
            str(row.get("category")),
        ),
        "microstructure": score_microstructure(
            float(spread) if spread is not None and pd.notna(spread) else None,
            max_spread,
        ),
        "volatility": score_volatility(atr_pct, gates),
        "trend": score_trend(
            htf_slope,
            float(feats.get("structure_score") or 0),
            bool(feats.get("trend_aligned")),
            gates,
        ),
        "momentum": score_momentum(
            float(feats.get("ret_24h") or 0),
            float(feats.get("ret_7d") or 0),
            float(feats.get("rsi") or 50),
        ),
        "relative_strength": score_relative_strength(
            float(feats.get("ret_24h") or 0),
            btc_ret_24h,
        ),
        "volume_quality": score_volume_quality(rvol, gates),
    }

    composite = 100.0 * (
        w.liquidity * parts["liquidity"]
        + w.microstructure * parts["microstructure"]
        + w.volatility * parts["volatility"]
        + w.trend * parts["trend"]
        + w.momentum * parts["momentum"]
        + w.relative_strength * parts["relative_strength"]
        + w.volume_quality * parts["volume_quality"]
    )

    hard_fail = any(
        r.startswith(("low_atr", "high_atr", "funding_extreme", "wide_spread")) for r in reasons
    )
    # flat_htf / low_rvol soft-fail: allow if composite still strong
    soft_only = [r for r in reasons if r.startswith(("flat_htf", "low_rvol"))]
    if soft_only and not hard_fail:
        composite *= 0.85
        reasons.extend(["soft_penalty"])

    if composite >= gates.min_composite and not hard_fail:
        reasons.append("pass")
        accepted = True
    else:
        if composite < gates.min_composite:
            reasons.append(f"low_score:{composite:.1f}")
        accepted = False

    # Keep top factor tags for explainability
    top = sorted(parts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    reasons.extend([f"top:{k}={v:.2f}" for k, v in top])

    return ScoreResult(
        composite=round(composite, 2),
        accepted=accepted,
        reasons=reasons,
        parts={k: round(v, 3) for k, v in parts.items()},
    )
