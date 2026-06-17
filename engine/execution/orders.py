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
        # Map our direction to Kalshi's yes/no contract + price field.
        kalshi_side = "yes" if side == "up" else "no"
        price_cents = max(1, min(99, round(price_prob * 100)))
        order = {
            "ticker": ticker,
            "action": action,
            "side": kalshi_side,
            "count": quantity,
            "type": "limit",
            "time_in_force": "fill_or_kill",
            "client_order_id": str(uuid.uuid4()),
            ("yes_price" if kalshi_side == "yes" else "no_price"): price_cents,
        }
        try:
            resp = await self.rest.place_order(order)
            oid = resp.get("order", {}).get("order_id", "")
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
