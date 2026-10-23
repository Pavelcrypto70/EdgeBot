"""Prune public whitelist to current ProofGates using stored OOS fields."""
from __future__ import annotations

import json
from pathlib import Path

from edgebot.research.proof import ProofGates

ROOT = Path(__file__).resolve().parents[1]
g = ProofGates()


def ok(row: dict) -> bool:
    n = int(row.get("trades_n") or 0)
    wr = float(row.get("winrate_pct") or 0) / 100.0
    oos_n = int(row.get("oos_n") or 0)
    oos_wr = float(row.get("oos_wr") or 0)
    oos_exp = float(row.get("oos_exp_r") or 0)
    fast = int(row.get("ema_fast") or 0)
    slow = int(row.get("ema_slow") or 0)
    tp = float(row.get("tp_r") or 0)
    if n < g.min_trades or wr < g.target_winrate:
        return False
    if oos_n < g.min_oos_trades or oos_wr < g.oos_target_winrate:
        return False
    if oos_exp < g.oos_min_expectancy_r:
        return False
    if slow - fast < 8:
        return False
    if tp < 1.2:
        return False
    return True


def main() -> None:
    for name in ("docs/data/whitelist.json", "docs/data/live.json"):
        path = ROOT / name
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            kept = [r for r in raw if ok(r)]
            dropped = [r["symbol"] for r in raw if not ok(r)]
            path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
            print(name, "kept", len(kept), "dropped", dropped)
        else:
            rows = list(raw.get("whitelist") or [])
            kept = [r for r in rows if ok(r)]
            dropped = [r["symbol"] for r in rows if not ok(r)]
            raw["whitelist"] = kept
            raw["whitelist_n"] = len(kept)
            raw["whitelist_heavy_n"] = sum(1 for r in kept if r.get("bucket") == "heavy")
            raw["whitelist_fast_n"] = sum(1 for r in kept if r.get("bucket") == "fast")
            raw["last_removed"] = sorted(set(list(raw.get("last_removed") or []) + dropped))
            raw["next_scan_hint_ru"] = (
                "Гейты: WR≥55%, ≥8 сделок, E[R]≥0, PF≥1, OOS≥3 с WR≥55%. "
                "Следующий полный скан ≈ каждый час."
            )
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            print(name, "kept", len(kept), "dropped", dropped)


if __name__ == "__main__":
    main()
