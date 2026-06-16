"""CF Benchmarks BRRNY index feed for hourly market settlement.

Hourly KXBTCD Kalshi markets settle on the CME CF Bitcoin Reference Rate NY
(BRRNY), published by CF Benchmarks approximately 5 minutes after each hour.
This is NOT the same as the live Coinbase/Binance spot price used by the
15-minute model.

BRRNY is a volume-weighted median of BTC-USD trade prices across constituent
exchanges in the 1-hour calculation window ending at the top of the hour. It is
published via CF Benchmarks' public REST API.

This module:
1. Fetches the latest BRRNY observation from CF Benchmarks.
2. Caches the last-known value so the settlement detection loop can compare
   to the market strike without re-fetching on every tick.

Reference: https://www.cfbenchmarks.com/data/indices/BRRNY

Note: if CF Benchmarks API is unavailable, we fall back to the last-known
Coinbase spot price with a warning — this is an approximation.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

log = logging.getLogger("brrny")

# CF Benchmarks public REST endpoint.
BRRNY_URL = "https://www.cfbenchmarks.com/api/v1/reference-rates/BRRNY/latest"


class BRRNYFeed:
    """Fetches and caches the most-recent BRRNY settlement price."""

    def __init__(self, cache_ttl_s: float = 120.0):
        self._client = httpx.AsyncClient(timeout=10.0)
        self._cache_ttl = cache_ttl_s
        self._value: Optional[float] = None
        self._fetched_at: float = 0.0
        self._fallback: Optional[float] = None  # latest Coinbase spot (set externally)

    @property
    def value(self) -> Optional[float]:
        """Latest known BRRNY price (or spot fallback)."""
        return self._value or self._fallback

    def set_spot_fallback(self, spot: float) -> None:
        """Update the Coinbase spot fallback used when BRRNY is unavailable."""
        self._fallback = spot

    async def close(self) -> None:
        await self._client.aclose()

    async def latest(self, force: bool = False) -> Optional[float]:
        """Return the latest BRRNY price, refreshing the cache if stale."""
        now = time.time()
        if not force and self._value is not None:
            if now - self._fetched_at < self._cache_ttl:
                return self._value
        try:
            resp = await self._client.get(BRRNY_URL)
            resp.raise_for_status()
            data = resp.json()
            # CF Benchmarks returns {"value": "37234.56", "timestamp": "..."}
            raw = data.get("value") or data.get("rate") or data.get("price")
            if raw is not None:
                self._value = float(raw)
                self._fetched_at = now
                log.debug("BRRNY fetched: %.2f", self._value)
                return self._value
            log.warning("BRRNY response missing value field: %s", data)
        except Exception as exc:  # noqa: BLE001
            log.warning("BRRNY fetch failed (using spot fallback): %s", exc)
        return self._fallback

    async def settlement_price(self) -> Optional[float]:
        """Return the price to use for hourly settlement.

        Tries BRRNY first; falls back to spot with a warning.
        """
        price = await self.latest()
        if price is None:
            log.error("No BRRNY or spot fallback available for hourly settlement")
        elif self._value is None:
            log.warning("Using spot fallback for BRRNY hourly settlement: %.2f", price)
        return price
