"""Hard, server-side risk controls and position sizing.

Every proposed order passes through ``RiskEngine.check`` before it can be sent.
Limits are intentionally conservative and enforced regardless of what the
strategy (or, later, an LLM) requests:

  * max_per_trade     - USD notional cap on a single order
  * max_per_window    - USD cap on combined exposure within one market window
  * max_exposure      - USD cap on total open exposure across all markets
  * daily_loss_limit  - realized loss in a day that halts new entries
  * max_drawdown_pct  - drop from peak equity that trips the circuit breaker

Sizing uses fractional Kelly on the model edge, then clamps to the caps above.
A tripped circuit breaker or kill switch blocks all new entries until reset.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

log = logging.getLogger("risk")


@dataclass
class RiskParams:
    max_per_trade: float = 20.0
    max_per_window: float = 60.0
    daily_loss_limit: float = 50.0
    max_exposure: float = 200.0
    max_drawdown_pct: float = 15.0
    kelly_fraction: float = 0.25

    def to_dict(self) -> dict:
        return {
            "max_per_trade": self.max_per_trade,
            "max_per_window": self.max_per_window,
            "daily_loss_limit": self.daily_loss_limit,
            "max_exposure": self.max_exposure,
            "max_drawdown_pct": self.max_drawdown_pct,
            "kelly_fraction": self.kelly_fraction,
        }

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, float(v))


@dataclass
class RiskCheck:
    ok: bool
    reason: str = ""
    # Recommended USD notional for the order after sizing/clamping.
    size_usd: float = 0.0
    quantity: int = 0


@dataclass
class RiskEngine:
    params: RiskParams
    peak_equity: float = 0.0
    realized_today: float = 0.0
    _day: date = field(default_factory=date.today)
    circuit_broken: bool = False
    kill_switched: bool = False

    def reset_day_if_needed(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self.realized_today = 0.0

    def record_equity(self, equity: float) -> None:
        """Track peak equity and trip the drawdown circuit breaker if exceeded."""
        self.peak_equity = max(self.peak_equity, equity)
        if self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity * 100.0
            if dd >= self.params.max_drawdown_pct and not self.circuit_broken:
                self.circuit_broken = True
                log.warning("Circuit breaker tripped: drawdown %.1f%%", dd)

    def record_realized(self, pnl: float) -> None:
        self.reset_day_if_needed()
        self.realized_today += pnl

    def trip_kill_switch(self) -> None:
        self.kill_switched = True
        log.warning("KILL SWITCH engaged")

    def reset(self) -> None:
        self.circuit_broken = False
        self.kill_switched = False

    def kelly_size(self, edge: float, price_prob: float, bankroll: float) -> float:
        """Fractional-Kelly stake in USD for a binary bet.

        For a contract bought at probability-price ``p`` (i.e. cost p, pays 1):
        net odds b = (1 - p)/p, win prob = p + edge. Kelly fraction
        f* = (b*q_win - q_lose)/b, scaled by ``kelly_fraction``.
        """
        p = min(max(price_prob, 1e-3), 1 - 1e-3)
        win = min(max(p + edge, 0.0), 1.0)
        lose = 1.0 - win
        b = (1.0 - p) / p
        if b <= 0:
            return 0.0
        f_star = (b * win - lose) / b
        f = max(0.0, f_star) * self.params.kelly_fraction
        return f * bankroll

    def check(
        self,
        *,
        edge: float,
        price_prob: float,
        bankroll: float,
        window_exposure: float,
        total_exposure: float,
    ) -> RiskCheck:
        """Validate and size a proposed entry. Returns RiskCheck with quantity."""
        self.reset_day_if_needed()

        if self.kill_switched:
            return RiskCheck(False, "kill switch engaged")
        if self.circuit_broken:
            return RiskCheck(False, "circuit breaker tripped (drawdown)")
        if self.realized_today <= -abs(self.params.daily_loss_limit):
            return RiskCheck(False, "daily loss limit reached")

        # Kelly-suggested stake, clamped by all caps.
        stake = self.kelly_size(edge, price_prob, bankroll)
        stake = min(stake, self.params.max_per_trade)
        stake = min(stake, self.params.max_per_window - window_exposure)
        stake = min(stake, self.params.max_exposure - total_exposure)
        if stake <= 0:
            return RiskCheck(False, "exposure caps leave no room")

        # Contracts: cost per contract = price_prob dollars (price in [0,1]).
        cost_per = max(price_prob, 1e-3)
        quantity = int(stake // cost_per)
        if quantity < 1:
            return RiskCheck(False, "sized below one contract")
        return RiskCheck(True, "ok", size_usd=quantity * cost_per, quantity=quantity)
