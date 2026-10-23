from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProofGates:
    """Whitelist только при рабочих цифрах на всём окне и на OOS."""

    min_trades: int = 8
    target_winrate: float = 0.55  # ≥ 55%
    min_expectancy_r: float = 0.0  # E[R] > 0
    min_profit_factor: float = 1.0
    min_oos_trades: int = 3
    oos_target_winrate: float = 0.55
    oos_min_expectancy_r: float = 0.0


def evaluate_proof(
    train: dict[str, Any],
    oos: dict[str, Any],
    *,
    bucket: str,
    gates: ProofGates | None = None,
    all_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Whitelist = MA с WR≥55%, ≥8 сделок, плюсовым E[R], PF≥1 и нормальным OOS."""
    g = gates or ProofGates()
    book = all_metrics or oos
    n = int(book.get("trades", 0) or 0)
    wr = float(book.get("winrate", 0) or 0)
    exp = float(book.get("expectancy_r", 0) or 0)
    pf = float(book.get("profit_factor", 0) or 0)
    wr_pct = wr * 100

    oos_n = int(oos.get("trades", 0) or 0)
    oos_wr = float(oos.get("winrate", 0) or 0)
    oos_exp = float(oos.get("expectancy_r", 0) or 0)
    oos_pf = float(oos.get("profit_factor", 0) or 0)

    reasons_ru: list[str] = []
    fails: list[str] = []

    if n < g.min_trades:
        fails.append("trades")
        reasons_ru.append(
            f"Мало сделок: {n}, нужно ≥ {g.min_trades}."
        )
    if wr < g.target_winrate:
        fails.append("winrate")
        reasons_ru.append(
            f"Винрейт {wr_pct:.0f}% — ниже цели {g.target_winrate * 100:.0f}%."
        )
    if exp < g.min_expectancy_r:
        fails.append("expectancy")
        reasons_ru.append(
            f"Мат.ожидание {exp:+.2f}R — нужно ≥ {g.min_expectancy_r:+.2f}R."
        )
    if pf < g.min_profit_factor and n >= g.min_trades:
        fails.append("profit_factor")
        reasons_ru.append(
            f"Profit factor {pf:.2f} — нужно ≥ {g.min_profit_factor:.1f}."
        )

    if oos_n < g.min_oos_trades:
        fails.append("oos_trades")
        reasons_ru.append(
            f"На проверке (OOS) мало сделок: {oos_n}, нужно ≥ {g.min_oos_trades}."
        )
    else:
        if oos_wr < g.oos_target_winrate:
            fails.append("oos_winrate")
            reasons_ru.append(
                f"OOS винрейт {oos_wr * 100:.0f}% — ниже {g.oos_target_winrate * 100:.0f}%."
            )
        if oos_exp < g.oos_min_expectancy_r:
            fails.append("oos_expectancy")
            reasons_ru.append(
                f"OOS мат.ожидание {oos_exp:+.2f}R — нужно ≥ 0."
            )
        if oos_pf < g.min_profit_factor:
            fails.append("oos_pf")
            reasons_ru.append(
                f"OOS profit factor {oos_pf:.2f} — нужно ≥ {g.min_profit_factor:.1f}."
            )

    passed = len(fails) == 0
    style = "тяжёлая" if bucket == "heavy" else "быстрая"

    if passed:
        headline = f"Винрейт {wr_pct:.0f}% — берём в whitelist"
        summary = (
            f"Рабочие средние ({style}): {n} сделок, WR {wr_pct:.0f}% "
            f"(цель ≥ {g.target_winrate * 100:.0f}%), E[R]={exp:+.2f}, PF={pf:.2f}. "
            f"OOS: {oos_n} сделок, WR {oos_wr * 100:.0f}%."
        )
        verdict = "В WHITELIST"
        verdict_short = f"{wr_pct:.0f}%"
    else:
        headline = f"Лучший найденный винрейт {wr_pct:.0f}% — пока слабо"
        summary = (
            f"Нужно: WR ≥ {g.target_winrate * 100:.0f}%, ≥{g.min_trades} сделок, "
            f"E[R]≥0, PF≥{g.min_profit_factor:.0f}, OOS ≥{g.min_oos_trades} с WR≥55%. "
            f"Сейчас: {n} сделок / OOS {oos_n}."
        )
        verdict = "СЛАБО"
        verdict_short = f"{wr_pct:.0f}%"

    bullets = "".join(f"<li>{r}</li>" for r in reasons_ru) if reasons_ru else (
        f"<li>Винрейт {wr_pct:.0f}% при {n} сделках — ок для эмулятора.</li>"
    )
    html = f"""
    <div class="proof-card {'ok' if passed else 'bad'}">
      <div class="proof-title">{headline}</div>
      <div class="proof-summary">{summary}</div>
      <ul class="proof-list">{bullets}</ul>
      <div class="proof-mini">
        Цель: WR ≥ {g.target_winrate * 100:.0f}%, ≥{g.min_trades} сделок,
        E[R]≥0, PF≥{g.min_profit_factor:.0f}; OOS ≥{g.min_oos_trades} с WR≥55%.
      </div>
    </div>
    """

    return {
        "whitelist": passed,
        "emulator": passed,
        "fails": fails,
        "reasons_ru": reasons_ru,
        "proof": f"{headline}. {summary}",
        "proof_html": html,
        "verdict": verdict,
        "verdict_short": verdict_short,
        "headline": headline,
        "winrate_pct": round(wr_pct, 1),
    }
