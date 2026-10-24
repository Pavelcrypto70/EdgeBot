from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProofGates:
    """
    Whitelist под асимметричный R:R (тейк ≥ ~2R, стоп = 1R).
    При тейке 2R безубыток по WR ≈ 35% до комиссий → цель WR ≥ 48–50% + плюсовой E[R].
    """

    min_trades: int = 8
    target_winrate: float = 0.50  # ≥ 50% (с тейком 2R этого достаточно)
    min_expectancy_r: float = 0.08  # средний плюс в R
    min_profit_factor: float = 1.25
    min_oos_trades: int = 3
    oos_target_winrate: float = 0.48
    oos_min_expectancy_r: float = 0.0
    min_take_profit_r: float = 1.8  # не пускаем почти 1:1


def _gates_for_bucket(bucket: str, base: ProofGates | None = None) -> ProofGates:
    """Fast жёстче по тейку; medium чуть мягче по числу сделок."""
    g = base or ProofGates()
    b = (bucket or "heavy").lower()
    if b == "fast":
        return ProofGates(
            min_trades=max(g.min_trades, 8),
            target_winrate=max(g.target_winrate, 0.48),
            min_expectancy_r=max(g.min_expectancy_r, 0.10),
            min_profit_factor=max(g.min_profit_factor, 1.30),
            min_oos_trades=g.min_oos_trades,
            oos_target_winrate=g.oos_target_winrate,
            oos_min_expectancy_r=g.oos_min_expectancy_r,
            min_take_profit_r=max(g.min_take_profit_r, 2.0),
        )
    if b == "medium":
        return ProofGates(
            min_trades=g.min_trades,
            target_winrate=g.target_winrate,
            min_expectancy_r=g.min_expectancy_r,
            min_profit_factor=g.min_profit_factor,
            min_oos_trades=g.min_oos_trades,
            oos_target_winrate=g.oos_target_winrate,
            oos_min_expectancy_r=g.oos_min_expectancy_r,
            min_take_profit_r=max(g.min_take_profit_r, 1.8),
        )
    return g


def evaluate_proof(
    train: dict[str, Any],
    oos: dict[str, Any],
    *,
    bucket: str,
    gates: ProofGates | None = None,
    all_metrics: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Whitelist = рабочий R:R + достаточный WR/OOS, не «высокий WR на тейке 1.2R»."""
    g = _gates_for_bucket(bucket, gates)
    book = all_metrics or oos
    n = int(book.get("trades", 0) or 0)
    wr = float(book.get("winrate", 0) or 0)
    exp = float(book.get("expectancy_r", 0) or 0)
    pf = float(book.get("profit_factor", 0) or 0)
    wr_pct = wr * 100
    tp_r = float((params or {}).get("take_profit_r") or (params or {}).get("tp_r") or 0)

    oos_n = int(oos.get("trades", 0) or 0)
    oos_wr = float(oos.get("winrate", 0) or 0)
    oos_exp = float(oos.get("expectancy_r", 0) or 0)
    oos_pf = float(oos.get("profit_factor", 0) or 0)

    reasons_ru: list[str] = []
    fails: list[str] = []

    if tp_r and tp_r < g.min_take_profit_r:
        fails.append("take_r")
        reasons_ru.append(
            f"Тейк {tp_r:.1f}R слишком близко к стопу (нужно ≥ {g.min_take_profit_r:.1f}R)."
        )

    if n < g.min_trades:
        fails.append("trades")
        reasons_ru.append(f"Мало сделок: {n}, нужно ≥ {g.min_trades}.")
    if wr < g.target_winrate:
        fails.append("winrate")
        reasons_ru.append(
            f"Винрейт {wr_pct:.0f}% — ниже цели {g.target_winrate * 100:.0f}% "
            f"(при тейке ≥{g.min_take_profit_r:.0f}R)."
        )
    if exp < g.min_expectancy_r:
        fails.append("expectancy")
        reasons_ru.append(
            f"Мат.ожидание {exp:+.2f}R — нужно ≥ {g.min_expectancy_r:+.2f}R."
        )
    if pf < g.min_profit_factor and n >= g.min_trades:
        fails.append("profit_factor")
        reasons_ru.append(
            f"Profit factor {pf:.2f} — нужно ≥ {g.min_profit_factor:.2f}."
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
            reasons_ru.append(f"OOS мат.ожидание {oos_exp:+.2f}R — нужно ≥ 0.")
        if oos_pf < 1.1:
            fails.append("oos_pf")
            reasons_ru.append(f"OOS profit factor {oos_pf:.2f} — слабо.")

    passed = len(fails) == 0
    _style = {"heavy": "медленная", "medium": "средняя", "fast": "быстрая"}
    style = _style.get((bucket or "").lower(), bucket or "MA")

    if passed:
        headline = f"WR {wr_pct:.0f}% · тейк {tp_r or '—'}R — в whitelist"
        summary = (
            f"Рабочие средние ({style}): {n} сделок, WR {wr_pct:.0f}%, "
            f"E[R]={exp:+.2f}, PF={pf:.2f}, тейк≈{tp_r or g.min_take_profit_r:.1f}R. "
            f"OOS: {oos_n} сделок, WR {oos_wr * 100:.0f}%."
        )
        verdict = "В WHITELIST"
        verdict_short = f"{wr_pct:.0f}%"
    else:
        headline = f"Лучший WR {wr_pct:.0f}% — пока слабо под R:R"
        summary = (
            f"Нужно: тейк ≥{g.min_take_profit_r:.1f}R, WR ≥{g.target_winrate * 100:.0f}%, "
            f"≥{g.min_trades} сделок, E[R]≥{g.min_expectancy_r:.2f}, PF≥{g.min_profit_factor:.2f}, "
            f"OOS ≥{g.min_oos_trades}. Сейчас: {n} / OOS {oos_n}, тейк={tp_r or '—'}."
        )
        verdict = "СЛАБО"
        verdict_short = f"{wr_pct:.0f}%"

    bullets = "".join(f"<li>{r}</li>" for r in reasons_ru) if reasons_ru else (
        f"<li>WR {wr_pct:.0f}% при тейке {tp_r or g.min_take_profit_r:.1f}R — ок.</li>"
    )
    html = f"""
    <div class="proof-card {'ok' if passed else 'bad'}">
      <div class="proof-title">{headline}</div>
      <div class="proof-summary">{summary}</div>
      <ul class="proof-list">{bullets}</ul>
      <div class="proof-mini">
        Цель: стоп=1R, тейк≥{g.min_take_profit_r:.1f}R, WR≥{g.target_winrate * 100:.0f}%,
        E[R]≥{g.min_expectancy_r:.2f}, PF≥{g.min_profit_factor:.2f}.
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
