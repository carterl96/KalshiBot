"""Async Kalshi REST client with RSA-PSS auth and simple rate limiting.

Wraps the small set of endpoints the engine needs: balance, markets, orderbook,
positions, and order placement/cancellation. Public market-data endpoints work
without auth; portfolio/order endpoints are signed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from engine.auth.signer import KalshiSigner

log = logging.getLogger("kalshi.rest")

# The REST path prefix that must be included in the signed path.
PATH_PREFIX = "/trade-api/v2"


class RateLimiter:
    """Token-bucket-ish limiter: at most `rate` calls per second."""

    def __init__(self, rate: float):
        self._min_interval = 1.0 / rate if rate > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class KalshiRestClient:
    def __init__(
        self,
        rest_base: str,
        signer: Optional[KalshiSigner] = None,
        rate: float = 8.0,
    ):
        self.rest_base = rest_base.rstrip("/")
        self.signer = signer
        self._limiter = RateLimiter(rate)
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _signed_path(self, path: str) -> str:
        """The full path used both for the URL and for signing (sans query)."""
        return f"{PATH_PREFIX}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = False,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> dict[str, Any]:
        await self._limiter.wait()
        url = f"{self.rest_base}{path}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth:
            if not self.signer:
                raise RuntimeError("Authenticated request requires a signer")
            sign_path = KalshiSigner.path_without_query(self._signed_path(path))
            headers.update(self.signer.headers(method, sign_path))

        resp = await self._client.request(
            method, url, headers=headers, params=params, json=json
        )
        if resp.status_code == 429:
            log.warning("Rate limited by Kalshi (429); backing off 1s")
            await asyncio.sleep(1.0)
            return await self._request(
                method, path, auth=auth, params=params, json=json
            )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # --- Public market data ---
    async def get_markets(self, **params) -> dict:
        return await self._request("GET", "/markets", params=params or None)

    async def get_market(self, ticker: str) -> dict:
        return await self._request("GET", f"/markets/{ticker}")

    async def get_orderbook(self, ticker: str, depth: int = 10) -> dict:
        return await self._request(
            "GET", f"/markets/{ticker}/orderbook", params={"depth": depth}
        )

    async def get_events(self, **params) -> dict:
        return await self._request("GET", "/events", params=params or None)

    # --- Authenticated portfolio / orders ---
    async def get_balance(self) -> dict:
        return await self._request("GET", "/portfolio/balance", auth=True)

    async def get_positions(self, **params) -> dict:
        return await self._request(
            "GET", "/portfolio/positions", auth=True, params=params or None
        )

    async def get_orders(self, **params) -> dict:
        return await self._request(
            "GET", "/portfolio/orders", auth=True, params=params or None
        )

    async def place_order(self, order: dict) -> dict:
        """Place an order. `order` follows Kalshi's CreateOrder schema, e.g.
        {ticker, action:"buy"|"sell", side:"yes"|"no", count, type:"limit",
         yes_price | no_price, client_order_id, time_in_force}."""
        return await self._request(
            "POST", "/portfolio/orders", auth=True, json=order
        )

    async def cancel_order(self, order_id: str) -> dict:
        return await self._request(
            "DELETE", f"/portfolio/orders/{order_id}", auth=True
        )
