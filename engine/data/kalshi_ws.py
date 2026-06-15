"""Kalshi market-data WebSocket client.

Maintains a live view of the order book for a set of market tickers by
subscribing to the ``orderbook_delta`` channel (snapshot + incremental deltas)
and the ``ticker`` channel. Optionally subscribes to private ``fill`` updates
when authenticated. Connection is authenticated during the handshake using the
same RSA-PSS scheme as REST (signing the WS path).

Order book state per ticker is kept as {price_cents: contracts} maps for the
yes and no sides, from which best bid/ask and mids are derived.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Optional

import websockets

from engine.auth.signer import KalshiSigner

log = logging.getLogger("feed.kalshi")

WS_PATH = "/trade-api/v2/ws/v2"


class OrderBook:
    """Simple aggregated book: maps of price(cents) -> resting contract count."""

    def __init__(self):
        self.yes: dict[int, int] = {}
        self.no: dict[int, int] = {}
        self.ts: float = 0.0

    def apply_snapshot(self, yes: list[list[int]], no: list[list[int]]) -> None:
        self.yes = {int(p): int(c) for p, c in (yes or [])}
        self.no = {int(p): int(c) for p, c in (no or [])}
        self.ts = time.time()

    def apply_delta(self, side: str, price: int, delta: int) -> None:
        book = self.yes if side == "yes" else self.no
        new = book.get(price, 0) + delta
        if new <= 0:
            book.pop(price, None)
        else:
            book[price] = new
        self.ts = time.time()

    def best_yes_bid(self) -> Optional[int]:
        return max(self.yes) if self.yes else None

    def best_no_bid(self) -> Optional[int]:
        return max(self.no) if self.no else None

    def yes_bid_ask(self) -> tuple[Optional[int], Optional[int]]:
        """Best YES bid and YES ask (in cents).

        A NO bid at price p implies a YES ask at (100 - p): selling NO at p is
        buying YES at 100 - p.
        """
        yes_bid = self.best_yes_bid()
        no_bid = self.best_no_bid()
        yes_ask = (100 - no_bid) if no_bid is not None else None
        return yes_bid, yes_ask

    def no_bid_ask(self) -> tuple[Optional[int], Optional[int]]:
        """Best NO bid and NO ask (in cents). A YES bid at p implies a NO ask
        at (100 - p)."""
        no_bid = self.best_no_bid()
        yes_bid = self.best_yes_bid()
        no_ask = (100 - yes_bid) if yes_bid is not None else None
        return no_bid, no_ask

    def ask_for(self, side: str) -> Optional[int]:
        """Cost (cents) to buy the given direction: 'up' -> YES ask,
        'down' -> NO ask."""
        if side == "up":
            return self.yes_bid_ask()[1]
        return self.no_bid_ask()[1]

    def mid(self) -> Optional[float]:
        bid, ask = self.yes_bid_ask()
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return float(bid if bid is not None else ask) if (bid or ask) else None


class KalshiWS:
    def __init__(
        self,
        ws_base: str,
        signer: Optional[KalshiSigner] = None,
    ):
        self.ws_base = ws_base
        self.signer = signer
        self.books: dict[str, OrderBook] = {}
        self.tickers: set[str] = set()
        self._on_update: Optional[Callable[[str, OrderBook], None]] = None
        self._on_fill: Optional[Callable[[dict], None]] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cmd_id = 0
        self._ws = None

    def on_book_update(self, cb: Callable[[str, OrderBook], None]) -> None:
        self._on_update = cb

    def on_fill(self, cb: Callable[[dict], None]) -> None:
        self._on_fill = cb

    def set_tickers(self, tickers: list[str]) -> None:
        self.tickers = set(tickers)

    def book(self, ticker: str) -> OrderBook:
        return self.books.setdefault(ticker, OrderBook())

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="kalshi-ws")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _auth_headers(self) -> dict[str, str]:
        if not self.signer:
            return {}
        path = KalshiSigner.path_without_query(WS_PATH)
        return self.signer.headers("GET", path)

    async def _run(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                headers = self._auth_headers()
                async with websockets.connect(
                    self.ws_base,
                    additional_headers=headers or None,
                    ping_interval=10,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    log.info("Kalshi WS connected (%d tickers)", len(self.tickers))
                    backoff = 1.0
                    await self._subscribe(ws)
                    async for raw in ws:
                        if not self._running:
                            break
                        self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Kalshi WS error: %s; reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                self._ws = None

    async def _subscribe(self, ws) -> None:
        if not self.tickers:
            return
        channels = ["orderbook_delta", "ticker"]
        if self.signer:
            channels.append("fill")
        self._cmd_id += 1
        cmd = {
            "id": self._cmd_id,
            "cmd": "subscribe",
            "params": {"channels": channels, "market_tickers": sorted(self.tickers)},
        }
        await ws.send(json.dumps(cmd))

    async def resubscribe(self, tickers: list[str]) -> None:
        """Update the subscription set (used as markets roll over)."""
        self.set_tickers(tickers)
        if self._ws is not None:
            try:
                await self._subscribe(self._ws)
            except Exception as exc:  # noqa: BLE001
                log.warning("resubscribe failed: %s", exc)

    def _handle(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        msg_type = msg.get("type")
        data = msg.get("msg", {})
        if msg_type == "orderbook_snapshot":
            ticker = data.get("market_ticker")
            if ticker:
                self.book(ticker).apply_snapshot(data.get("yes", []), data.get("no", []))
                self._emit(ticker)
        elif msg_type == "orderbook_delta":
            ticker = data.get("market_ticker")
            if ticker:
                self.book(ticker).apply_delta(
                    data.get("side"), int(data.get("price")), int(data.get("delta"))
                )
                self._emit(ticker)
        elif msg_type == "fill":
            if self._on_fill:
                self._on_fill(data)

    def _emit(self, ticker: str) -> None:
        if self._on_update:
            self._on_update(ticker, self.book(ticker))
