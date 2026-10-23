from __future__ import annotations

from typing import Any

import httpx

from edgebot.config import get_settings


class BybitClient:
    """Minimal Bybit v5 public client (tickers / klines / funding)."""

    MAINNET = "https://api.bybit.com"
    TESTNET = "https://api-testnet.bybit.com"

    def __init__(self, *, timeout: float = 30.0) -> None:
        settings = get_settings()
        base = self.TESTNET if settings.bybit_testnet else self.MAINNET
        # Market data is richer on mainnet public even if trading later uses testnet
        self.public_url = self.MAINNET if settings.bybit_data_host == "public" else base
        # connect/read timeouts — скринер не должен висеть минутами
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=8.0, read=timeout, write=8.0, pool=8.0)
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BybitClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get_public(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self._client.get(f"{self.public_url}{path}", params=params or {})
        r.raise_for_status()
        payload = r.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}")
        return payload["result"]

    def tickers(self, category: str) -> list[dict[str, Any]]:
        result = self._get_public("/v5/market/tickers", {"category": category})
        return list(result.get("list") or [])

    def klines(
        self,
        category: str,
        symbol: str,
        interval: str | int,
        *,
        limit: int = 200,
    ) -> list[list[str]]:
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "interval": str(interval),
            "limit": min(limit, 1000),
        }
        result = self._get_public("/v5/market/kline", params)
        rows = list(result.get("list") or [])
        rows.reverse()  # oldest → newest
        return rows

    def funding_rate(self, symbol: str) -> float | None:
        try:
            result = self._get_public(
                "/v5/market/tickers",
                {"category": "linear", "symbol": symbol},
            )
            items = list(result.get("list") or [])
            if not items:
                return None
            raw = items[0].get("fundingRate")
            return float(raw) if raw not in (None, "") else None
        except Exception:
            return None
