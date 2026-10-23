from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProofGates:
    """Простые правила: нормальный винрейт + достаточно сделок."""

    min_trades: int = 10
    target_winrate: float = 0.55  # 55%
    # при хорошем WR не режем из‑за мелкого минуса в R
    min_expectancy_r: float = -0.35


def evaluate_proof(
    train: dict[str, Any],
    oos: dict[str, Any],
    *,
    bucket: str,
    gates: ProofGates | None = None,
    all_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Whitelist = нашли набор MA с нормальным % побед."""
    g = gates or ProofGates()
    book = all_metrics or oos
    n = int(book.get("trades", 0) or 0)
    wr = float(book.get("winrate", 0) or 0)
    exp = float(book.get("expectancy_r", 0) or 0)
    wr_pct = wr * 100

    oos_n = int(oos.get("trades", 0) or 0)
    oos_wr = float(oos.get("winrate", 0) or 0)

    reasons_ru: list[str] = []
    fails: list[str] = []

    if n < g.min_trades:
        fails.append("trades")
        reasons_ru.append(
            f"Мало сделок для вывода: {n}, нужно хотя бы {g.min_trades}."
        )
    if wr < g.target_winrate:
        fails.append("winrate")
        reasons_ru.append(
            f"Винрейт {wr_pct:.0f}% — ниже цели {g.target_winrate*100:.0f}%."
        )
    if exp < g.min_expectancy_r:
        fails.append("expectancy")
        reasons_ru.append(
            f"В среднем сделка слегка в минусе ({exp:+.2f} риска). Ищем лучше."
        )

    passed = len(fails) == 0
    style = "тяжёлая" if bucket == "heavy" else "быстрая"

    if passed:
        headline = f"Винрейт {wr_pct:.0f}% — берём в whitelist"
        summary = (
            f"На активной монете найдены рабочие средние ({style}). "
            f"Сделок: {n}. Прибыльных: {wr_pct:.0f}% (цель ≥ {g.target_winrate*100:.0f}%)."
        )
        if oos_n > 0:
            summary += f" На свежем куске: {oos_n} сделок, винрейт {oos_wr*100:.0f}%."
        verdict = "В WHITELIST"
        verdict_short = f"{wr_pct:.0f}%"
    else:
        headline = f"Лучший найденный винрейт {wr_pct:.0f}% — пока слабо"
        summary = (
            f"Перебрали сетку средних. Пока не дотянули до {g.target_winrate*100:.0f}% "
            f"при ≥{g.min_trades} сделках (сейчас {n} сделок)."
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
        Цель: винрейт ≥ {g.target_winrate*100:.0f}% и минимум {g.min_trades} сделок.
        Средний результат сделки: {exp:+.2f} риска.
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
