"""Real-time crypto spot price feed via the Coinbase Exchange WebSocket.

Subscribes to the public ``ticker`` channel for the configured products
(e.g. BTC-USD, ETH-USD) and keeps the latest price per product. This spot price
is the input to the fair-value model. No authentication required.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Optional

import websockets

log = logging.getLogger("feed.spot")

COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"


class SpotFeed:
    def __init__(self, products: list[str]):
        self.products = products
        self.prices: dict[str, float] = {}
        self.last_update: dict[str, float] = {}
        self._on_tick: Optional[Callable[[str, float, float], None]] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def on_tick(self, cb: Callable[[str, float, float], None]) -> None:
        """Register a callback invoked as cb(product, price, ts) on each tick."""
        self._on_tick = cb

    def get(self, product: str) -> Optional[float]:
        return self.prices.get(product)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="spot-feed")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(
                    COINBASE_WS, ping_interval=20, ping_timeout=10
                ) as ws:
                    sub = {
                        "type": "subscribe",
                        "product_ids": self.products,
                        "channels": ["ticker"],
                    }
                    await ws.send(json.dumps(sub))
                    log.info("Spot feed connected for %s", self.products)
                    backoff = 1.0
                    async for raw in ws:
                        if not self._running:
                            break
                        self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on any error
                log.warning("Spot feed error: %s; reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _handle(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if msg.get("type") != "ticker":
            return
        product = msg.get("product_id")
        price_str = msg.get("price")
        if not product or price_str is None:
            return
        try:
            price = float(price_str)
        except (TypeError, ValueError):
            return
        ts = time.time()
        self.prices[product] = price
        self.last_update[product] = ts
        if self._on_tick:
            self._on_tick(product, price, ts)
