from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edgebot.config import ROOT, load_config
from edgebot.research.pipeline import run_proof_research
from edgebot.research.pipeline_cross import run_cross_heavy_research

PUBLIC_DIR = ROOT / "docs" / "data"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _row_key(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or "")


def _slim(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "symbol",
        "category",
        "bucket",
        "strategy",
        "ema_fast",
        "ema_slow",
        "atr_mult",
        "tp_r",
        "htf_slope_min",
        "winrate_pct",
        "trades_n",
        "oos_n",
        "oos_wr",
        "oos_exp_r",
        "verdict",
        "verdict_short",
        "whitelist",
    ]
    out = {k: row.get(k) for k in keys if k in row}
    out["symbol"] = str(row.get("symbol") or "")
    out["whitelist"] = bool(row.get("whitelist"))
    return out


def merge_whitelist(
    previous: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Новый скан = источник правды. Возвращает (итог, добавленные, убранные)."""
    prev_map = {_row_key(r): r for r in previous if _row_key(r)}
    fresh_map = {_row_key(r): _slim(r) for r in fresh if _row_key(r) and r.get("whitelist")}
    prev_set = set(prev_map)
    fresh_set = set(fresh_map)
    added = sorted(fresh_set - prev_set)
    removed = sorted(prev_set - fresh_set)
    merged = [fresh_map[s] for s in sorted(fresh_set)]
    return merged, added, removed


def run_autonomous_cycle(
    *,
    max_heavy: int = 10,
    max_fast: int = 8,
    do_proof: bool = True,
    do_cross: bool = True,
    quiet: bool = False,
) -> dict[str, Any]:
    """
    Полный автономный цикл:
    1) Proof MA + кресты heavy
    2) объединение whitelist
    3) diff с прошлым live.json
    4) запись docs/data/* для GitHub Pages
    """
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    live_path = PUBLIC_DIR / "live.json"
    history_path = PUBLIC_DIR / "history.json"
    scans_dir = PUBLIC_DIR / "scans"
    scans_dir.mkdir(exist_ok=True)

    cfg = load_config()
    prev_live = _read_json(live_path, {})
    previous_wl = list(prev_live.get("whitelist") or [])

    all_rows: list[dict[str, Any]] = []
    sources: list[str] = []

    def _log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    scan_error: str | None = None
    try:
        if do_cross:
            _log("=== автономный скан: кресты heavy ===")
            cross = run_cross_heavy_research(cfg=cfg, max_heavy=max_heavy, quiet=quiet)
            if not cross.results.empty:
                all_rows.extend(cross.results.to_dict(orient="records"))
                sources.append("cross")
            _log(f"кресты: WL {len(cross.whitelist)} / {len(cross.results)}")

        if do_proof:
            _log("=== автономный скан: Proof MA ===")
            proof = run_proof_research(
                cfg=cfg, max_heavy=max_heavy, max_fast=max_fast, quiet=quiet
            )
            if not proof.results.empty:
                all_rows.extend(proof.results.to_dict(orient="records"))
                sources.append("proof")
            _log(f"proof: WL {len(proof.whitelist)} / {len(proof.results)}")
    except Exception as exc:  # noqa: BLE001
        scan_error = str(exc)
        _log(f"скан упал: {scan_error}")
        if previous_wl:
            _log("оставляем прошлый whitelist, сайт не обнуляем")
            live = dict(prev_live) if isinstance(prev_live, dict) else {}
            live.update(
                {
                    "updated_at": _now_iso(),
                    "status": "degraded",
                    "last_error": scan_error,
                    "whitelist": previous_wl,
                    "whitelist_n": len(previous_wl),
                    "next_scan_hint_ru": "Скан сбойнул (часто 403 Bybit с облака). Данные прошлые, сайт жив.",
                }
            )
            _write_json(live_path, live)
            try:
                from edgebot.cloud.trading_book import update_trading_book

                update_trading_book(previous_wl, quiet=quiet)
            except Exception as book_exc:  # noqa: BLE001
                _log(f"торговая книга: {book_exc}")
            return live
        raise

    # Если одна монета прошла в нескольких прогонах — берём с лучшим winrate
    best: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        if not row.get("whitelist"):
            continue
        sym = _row_key(row)
        if not sym:
            continue
        cand = _slim(row)
        old = best.get(sym)
        if old is None or float(cand.get("winrate_pct") or 0) >= float(old.get("winrate_pct") or 0):
            best[sym] = cand

    fresh_wl = list(best.values())
    merged, added, removed = merge_whitelist(previous_wl, fresh_wl)

    ts = _now_iso()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "run_id": run_id,
        "ts": ts,
        "sources": sources,
        "researched": len(all_rows),
        "whitelist_n": len(merged),
        "added": added,
        "removed": removed,
        "whitelist": merged,
        "order": {"margin_usdt": 100, "leverage": 3, "notional_usdt": 300},
        "balance_start_usdt": 1000,
        "note_ru": "Автоскан на серверах GitHub. Компьютер владельца может быть выключен.",
    }

    live = {
        "updated_at": ts,
        "run_id": run_id,
        "status": "ok",
        "whitelist": merged,
        "whitelist_n": len(merged),
        "last_added": added,
        "last_removed": removed,
        "order": snapshot["order"],
        "balance_start_usdt": 1000,
        "next_scan_hint_ru": "Следующий скан по расписанию ≈ каждые 4 часа",
        "history_preview": {
            "added": added,
            "removed": removed,
        },
    }

    history = _read_json(history_path, [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "run_id": run_id,
            "ts": ts,
            "whitelist_n": len(merged),
            "added": added,
            "removed": removed,
            "symbols": [r["symbol"] for r in merged],
            "sources": sources,
        }
    )
    history = history[-200:]

    _write_json(live_path, live)
    _write_json(history_path, history)
    _write_json(scans_dir / f"{run_id}.json", snapshot)

    # плоский CSV-подобный JSON для удобства скачивания данных
    _write_json(PUBLIC_DIR / "whitelist.json", merged)

    try:
        from edgebot.cloud.trading_book import update_trading_book

        book = update_trading_book(merged, quiet=quiet)
        live["trading_equity"] = book.get("equity_usdt")
        live["trading_wr"] = book.get("winrate_pct")
        _write_json(live_path, live)
    except Exception as book_exc:  # noqa: BLE001
        _log(f"торговая книга: {book_exc}")

    _log(f"готово · WL={len(merged)} · +{added} · -{removed} · {live_path}")
    return live
