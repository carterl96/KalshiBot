"""Order execution and position tracking (paper + live).

In paper mode, orders fill immediately at the requested price against a
simulated bankroll — the identical decision pipeline runs against live market
data, only the fill is simulated. In live mode, orders are sent to Kalshi via
the signed REST client with hard caps already enforced upstream by the risk
engine.

Positions are tracked per market window so the strategy can scale in, hedge the
opposite side, or flatten near close. Settlement is handled by ``settle`` when a
market resolves.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from engine.auth.rest_client import KalshiRestClient

log = logging.getLogger("execution")


@dataclass
class Position:
    ticker: str
    side: str               # up | down
    quantity: int = 0
    avg_price: float = 0.0  # probability price [0,1]

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_price

    def add(self, qty: int, price: float) -> None:
        total = self.quantity + qty
        if total <= 0:
            self.quantity = 0
            self.avg_price = 0.0
            return
        self.avg_price = (self.cost_basis + qty * price) / total
        self.quantity = total


@dataclass
class ExecutionResult:
    ok: bool
    ticker: str
    side: str
    action: str
    quantity: int
    price: float
    mode: str
    reason: str = ""
    order_id: str = ""
    pnl: float = 0.0


@dataclass
class OrderManager:
    rest: Optional[KalshiRestClient]
    mode: str = "paper"                      # paper | live
    balance: float = 1000.0                  # USD (paper bankroll / cash)
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0

    def _key(self, ticker: str, side: str) -> str:
        return f"{ticker}:{side}"

    def position(self, ticker: str, side: str) -> Position:
        key = self._key(ticker, side)
        return self.positions.setdefault(key, Position(ticker=ticker, side=side))

    def window_exposure(self, ticker: str) -> float:
        return sum(
            p.cost_basis for k, p in self.positions.items() if k.startswith(ticker + ":")
        )

    def total_exposure(self) -> float:
        return sum(p.cost_basis for p in self.positions.values())

    def equity(self, mark: Optional[dict[str, float]] = None) -> float:
        """Cash + marked-to-market value of open positions.

        ``mark`` maps "ticker:side" -> current probability price. Absent a mark,
        positions are held at cost.
        """
        mark = mark or {}
        pos_value = 0.0
        for key, p in self.positions.items():
            price = mark.get(key, p.avg_price)
            pos_value += p.quantity * price
        return self.balance + pos_value

    async def buy(
        self, ticker: str, side: str, quantity: int, price_prob: float, reason: str = ""
    ) -> ExecutionResult:
        """Buy ``quantity`` contracts of ``side`` at ``price_prob`` (in [0,1])."""
        cost = quantity * price_prob
        if cost > self.balance + 1e-9:
            return ExecutionResult(
                False, ticker, side, "buy", 0, price_prob, self.mode,
                reason="insufficient balance",
            )

        if self.mode == "live":
            placed = await self._place_live(ticker, side, quantity, price_prob, "buy")
            if not placed.ok:
                return placed

        self.balance -= cost
        self.position(ticker, side).add(quantity, price_prob)
        log.info(
            "[%s] BUY %d %s %s @ %.2f (%s)",
            self.mode, quantity, ticker, side, price_prob, reason,
        )
        return ExecutionResult(
            True, ticker, side, "buy", quantity, price_prob, self.mode, reason=reason
        )

    async def sell(
        self, ticker: str, side: str, quantity: int, price_prob: float, reason: str = ""
    ) -> ExecutionResult:
        """Sell (close) ``quantity`` contracts of ``side`` at ``price_prob``."""
        pos = self.position(ticker, side)
        quantity = min(quantity, pos.quantity)
        if quantity <= 0:
            return ExecutionResult(
                False, ticker, side, "sell", 0, price_prob, self.mode,
                reason="no position",
            )

        if self.mode == "live":
            placed = await self._place_live(ticker, side, quantity, price_prob, "sell")
            if not placed.ok:
                return placed

        proceeds = quantity * price_prob
        pnl = quantity * (price_prob - pos.avg_price)
        self.balance += proceeds
        self.realized_pnl += pnl
        pos.add(-quantity, price_prob)
        log.info(
            "[%s] SELL %d %s %s @ %.2f pnl=%.2f (%s)",
            self.mode, quantity, ticker, side, price_prob, pnl, reason,
        )
        return ExecutionResult(
            True, ticker, side, "sell", quantity, price_prob, self.mode,
            reason=reason, pnl=pnl,
        )

    def settle(self, ticker: str, up_wins: bool) -> float:
        """Settle all positions for a resolved market. Returns realized pnl."""
        pnl_total = 0.0
        for side in ("up", "down"):
            key = self._key(ticker, side)
            pos = self.positions.get(key)
            if not pos or pos.quantity <= 0:
                continue
            won = (side == "up" and up_wins) or (side == "down" and not up_wins)
            payoff = pos.quantity * (1.0 if won else 0.0)
            pnl = payoff - pos.cost_basis
            self.balance += payoff
            self.realized_pnl += pnl
            pnl_total += pnl
            log.info("SETTLE %s %s won=%s pnl=%.2f", ticker, side, won, pnl)
            self.positions.pop(key, None)
        return pnl_total

    async def _place_live(
        self, ticker: str, side: str, quantity: int, price_prob: float, action: str
    ) -> ExecutionResult:
        if not self.rest:
            return ExecutionResult(
                False, ticker, side, action, 0, price_prob, self.mode,
                reason="no REST client for live order",
            )
        # Kalshi V2 event-order API is YES-denominated: side "bid" = buy YES,
        # "ask" = sell YES, with one `price` (the YES price) in dollar fixed-point.
        #   buy  up   -> bid @ yes_price = price_prob       (buy YES)
        #   sell up   -> ask @ yes_price = price_prob       (sell YES)
        #   buy  down -> ask @ yes_price = 1 - price_prob   (sell YES == buy NO)
        #   sell down -> bid @ yes_price = 1 - price_prob   (buy YES == sell NO)
        if side == "up":
            api_side = "bid" if action == "buy" else "ask"
            yes_price = price_prob
        else:
            api_side = "ask" if action == "buy" else "bid"
            yes_price = 1.0 - price_prob
        yes_price = min(max(yes_price, 0.01), 0.99)
        order = {
            "ticker": ticker,
            "side": api_side,
            "count": f"{quantity:.2f}",
            "price": f"{yes_price:.4f}",
            "time_in_force": "fill_or_kill",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": str(uuid.uuid4()),
        }
        try:
            resp = await self.rest.place_order(order)
            oid = resp.get("order_id") or resp.get("order", {}).get("order_id", "")
            return ExecutionResult(
                True, ticker, side, action, quantity, price_prob, self.mode,
                order_id=oid,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("live order failed: %s", exc)
            return ExecutionResult(
                False, ticker, side, action, 0, price_prob, self.mode,
                reason=f"live order error: {exc}",
            )

    async def sync_live_balance(self) -> None:
        """Pull the real account cash balance when running live."""
        if self.mode == "live" and self.rest:
            try:
                bal = await self.rest.get_balance()
                # Kalshi returns balance in cents.
                self.balance = float(bal.get("balance", 0)) / 100.0
            except Exception as exc:  # noqa: BLE001
                log.warning("balance sync failed: %s", exc)

    def reset_positions(self) -> None:
        """Drop all in-memory positions (used when switching modes so paper
        positions never leak into live trading, and vice versa)."""
        self.positions.clear()

    async def reconcile_live_positions(self) -> None:
        """Replace the in-memory book with the broker's real open positions.

        Called when entering live mode (or starting live) so the engine's view
        matches the actual Kalshi account instead of stale paper fills. On a
        fresh account this simply yields an empty book.
        """
        self.positions.clear()
        if not (self.mode == "live" and self.rest and self.rest.signer):
            return
        try:
            resp = await self.rest.get_positions()
        except Exception as exc:  # noqa: BLE001
            log.warning("position reconcile failed: %s", exc)
            return
        count = 0
        for mp in resp.get("market_positions", []):
            ticker = mp.get("ticker")
            net = int(mp.get("position", 0) or 0)
            if not ticker or net == 0:
                continue
            # Kalshi: positive position = long YES (up), negative = long NO (down).
            side = "up" if net > 0 else "down"
            qty = abs(net)
            exposure_cents = abs(float(mp.get("market_exposure", 0) or 0))
            avg_price = min(max(exposure_cents / qty / 100.0, 0.0), 1.0) if qty else 0.0
            self.position(ticker, side).add(qty, avg_price)
            count += 1
        log.info("Reconciled %d live position(s) from Kalshi", count)
