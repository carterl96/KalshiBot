"""Tick data collector: persist Kalshi order-book snapshots to the DB.

On each evaluation cycle the engine can call ``record()`` to write a compact
snapshot (spot, vol, Kalshi ask, model prob) to the ``market_ticks`` table.
These rows are the raw material for the backtesting harness — export them with
``GET /api/ticks?ticker=...`` and feed them to ``BacktestRunner``.

The collector deduplicates: it stores at most one snapshot per (ticker, side)
per ``interval_s`` seconds to avoid bloating the DB with 500ms-frequency rows.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("tick_collector")


@dataclass
class TickRow:
    ticker: str
    side: str
    ts: float
    strike: float
    spot: float
    sigma: float
    tau: float
    ask_cents: int
    model_prob: float
    outcome: int | None = None  # resolved after settlement


class TickCollector:
    def __init__(self, store, interval_s: float = 60.0):
        self._store = store
        self._interval = interval_s
        self._last: dict[str, float] = {}  # "ticker:side" → last stored ts

    def should_record(self, ticker: str, side: str) -> bool:
        key = f"{ticker}:{side}"
        now = time.time()
        last = self._last.get(key, 0.0)
        return now - last >= self._interval

    def mark_recorded(self, ticker: str, side: str) -> None:
        self._last[f"{ticker}:{side}"] = time.time()

    async def record(
        self,
        ticker: str,
        side: str,
        strike: float,
        spot: float,
        sigma: float,
        tau: float,
        ask_cents: int,
        model_prob: float,
    ) -> None:
        """Persist one snapshot (deduped per interval)."""
        if not self.should_record(ticker, side):
            return
        await self._store.add_tick(
            ticker=ticker,
            side=side,
            ts=time.time(),
            strike=strike,
            spot=spot,
            sigma=sigma,
            tau=tau,
            ask_cents=ask_cents,
            model_prob=model_prob,
        )
        self.mark_recorded(ticker, side)

    async def resolve(self, ticker: str, up_wins: bool) -> None:
        """Set outcome on all stored ticks for a resolved ticker."""
        await self._store.resolve_ticks(ticker, up_wins)
