"""Backtesting harness: replay historical ticks through the pricing pipeline.

The runner does NOT require live market data or a database — it accepts a list
of ``Tick`` snapshots (historical records of spot price + Kalshi book) and
replays them through the same ``evaluate`` → risk-check → paper-fill logic used
in production. This lets you:

  * validate that the edge model generates positive expectation on real data
  * tune ``min_edge`` / ``kelly_fraction`` / ``fee_buffer`` before live
  * compute Brier scores against known historical outcomes

Input format
------------
Each ``Tick`` captures one snapshot of a single market window:
  - ``ts``        Unix timestamp (float)
  - ``ticker``    Kalshi market ticker
  - ``side``      "up" | "down"
  - ``strike``    market strike price (USD)
  - ``spot``      BTC (or ETH) spot price at that moment
  - ``sigma``     annualised realised vol at that moment
  - ``tau``       seconds to close at that moment
  - ``ask_cents`` Kalshi ask price in cents (1–99) for this side
  - ``outcome``   1 = this side resolved YES, 0 = resolved NO
                  (required for P&L and Brier-score calculation)

You can produce these ticks by replaying exported Kalshi orderbook snapshots
alongside a Coinbase 1-minute kline file.

Usage
-----
>>> from engine.backtest.runner import BacktestRunner, Tick
>>> from engine.backtest.runner import BacktestParams
>>>
>>> ticks = [...]   # list[Tick]
>>> params = BacktestParams(min_edge=0.04, fee_buffer=0.02, kelly_fraction=0.25)
>>> result = BacktestRunner(params).run(ticks)
>>> print(result.summary())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from engine.execution.orders import OrderManager
from engine.execution.window import WindowManager
from engine.pricing.model import fair_prob
from engine.risk.limits import RiskEngine, RiskParams
from engine.strategy.edge import Signal

log = logging.getLogger("backtest")


@dataclass
class Tick:
    ts: float
    ticker: str
    side: str          # "up" | "down"
    strike: float
    spot: float
    sigma: float       # annualised realised vol
    tau: float         # seconds to close
    ask_cents: int     # Kalshi ask for this side in cents
    outcome: int       # 1 if this side resolved YES, 0 if NO


@dataclass
class BacktestParams:
    starting_balance: float = 1000.0
    min_edge: float = 0.04
    fee_buffer: float = 0.02
    kelly_fraction: float = 0.25
    max_per_trade: float = 20.0
    max_per_window: float = 60.0
    max_exposure: float = 200.0
    daily_loss_limit: float = 50.0
    max_drawdown_pct: float = 15.0


@dataclass
class TradeRecord:
    ts: float
    ticker: str
    side: str
    action: str         # "entry" | "scale_in" | "hedge" | "settle" | "take_profit" | "cut_loss"
    quantity: int
    price: float        # probability price [0,1]
    pnl: float = 0.0


@dataclass
class BacktestResult:
    params: BacktestParams
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[tuple[float, float]] = field(default_factory=list)
    predictions: list[tuple[float, int]] = field(default_factory=list)  # (model_prob, outcome)

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.params.starting_balance

    @property
    def total_pnl(self) -> float:
        return self.final_equity - self.params.starting_balance

    @property
    def pnl_pct(self) -> float:
        start = self.params.starting_balance
        return (self.total_pnl / start * 100.0) if start > 0 else 0.0

    @property
    def brier_score(self) -> Optional[float]:
        resolved = [(p, o) for p, o in self.predictions if o in (0, 1)]
        if not resolved:
            return None
        return sum((p - o) ** 2 for p, o in resolved) / len(resolved)

    @property
    def win_rate(self) -> Optional[float]:
        settled = [t for t in self.trades if t.action == "settle"]
        wins = [t for t in settled if t.pnl > 0]
        if not settled:
            return None
        return len(wins) / len(settled)

    @property
    def n_trades(self) -> int:
        return sum(1 for t in self.trades if t.action in ("entry", "scale_in", "hedge"))

    def summary(self) -> str:
        lines = [
            "=== Backtest Results ===",
            f"  Trades:      {self.n_trades}",
            f"  Final equity: ${self.final_equity:.2f}",
            f"  Total P&L:   ${self.total_pnl:+.2f} ({self.pnl_pct:+.1f}%)",
            f"  Win rate:    {f'{self.win_rate*100:.1f}%' if self.win_rate is not None else '—'}",
            f"  Brier score: {f'{self.brier_score:.4f}' if self.brier_score is not None else '—'}",
            f"  Equity points: {len(self.equity_curve)}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "final_equity": round(self.final_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "pnl_pct": round(self.pnl_pct, 2),
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "brier_score": round(self.brier_score, 4) if self.brier_score is not None else None,
            "n_equity_points": len(self.equity_curve),
            "n_predictions": len(self.predictions),
        }


class BacktestRunner:
    """Run the pricing → edge → risk → paper-fill pipeline on historical ticks."""

    def __init__(self, params: BacktestParams):
        self.params = params

    def run(self, ticks: list[Tick]) -> BacktestResult:
        """Replay ``ticks`` in chronological order and return results."""
        p = self.params
        risk = RiskEngine(
            RiskParams(
                max_per_trade=p.max_per_trade,
                max_per_window=p.max_per_window,
                daily_loss_limit=p.daily_loss_limit,
                max_exposure=p.max_exposure,
                max_drawdown_pct=p.max_drawdown_pct,
                kelly_fraction=p.kelly_fraction,
            )
        )
        orders = OrderManager(rest=None, mode="paper", balance=p.starting_balance)
        window_mgr = WindowManager()
        result = BacktestResult(params=p)

        # Group ticks by window (ticker) and sort chronologically.
        sorted_ticks = sorted(ticks, key=lambda t: t.ts)
        # Track which windows have been settled.
        settled: set[str] = set()
        # Track last tick per ticker to detect close.
        last_by_ticker: dict[str, Tick] = {}

        for tick in sorted_ticks:
            ticker = tick.ticker
            last_by_ticker[ticker] = tick

            # Settle any windows that have closed.
            if ticker not in settled and tick.tau <= 0:
                self._settle(ticker, tick, orders, window_mgr, risk, result)
                settled.add(ticker)
                continue

            if ticker in settled:
                continue

            # Compute fair probability and edge.
            model_p = fair_prob(tick.side, tick.spot, tick.strike, tick.sigma, tick.tau)
            ask_prob = tick.ask_cents / 100.0
            edge = model_p - ask_prob - p.fee_buffer

            result.predictions.append((model_p, tick.outcome))

            # Near-close exit checks.
            pos = orders.position(ticker, tick.side)
            if pos.quantity > 0:
                if window_mgr.should_take_profit(ticker, tick.side, model_p, tick.tau):
                    self._close(ticker, tick.side, pos, ask_prob, "take_profit", orders, result)
                    continue
                if window_mgr.should_cut_loss(ticker, tick.side, model_p, tick.tau):
                    self._close(ticker, tick.side, pos, ask_prob, "cut_loss", orders, result)
                    continue

            if edge < p.min_edge:
                continue

            check = risk.check(
                edge=edge,
                price_prob=ask_prob,
                bankroll=orders.balance,
                window_exposure=orders.window_exposure(ticker),
                total_exposure=orders.total_exposure(),
            )
            if not check.ok or check.quantity < 1:
                continue

            # Determine label (entry vs scale-in).
            if not (window_mgr.can_entry(ticker, tick.side) or
                    window_mgr.can_scale_in(ticker, tick.side)):
                continue

            label = window_mgr.entry_label(ticker, tick.side)
            cost = check.quantity * ask_prob
            if cost > orders.balance + 1e-9:
                continue

            orders.balance -= cost
            orders.position(ticker, tick.side).add(check.quantity, ask_prob)
            window_mgr.record_entry(ticker, tick.side)
            result.trades.append(
                TradeRecord(
                    ts=tick.ts, ticker=ticker, side=tick.side, action=label,
                    quantity=check.quantity, price=ask_prob,
                )
            )
            # Equity snapshot.
            equity = orders.balance + sum(p.cost_basis for p in orders.positions.values())
            risk.record_equity(equity)
            result.equity_curve.append((tick.ts, equity))

        # Settle any windows still open at the end of the tick stream.
        for ticker, tick in last_by_ticker.items():
            if ticker not in settled:
                self._settle(ticker, tick, orders, window_mgr, risk, result)

        return result

    def _settle(
        self,
        ticker: str,
        tick: Tick,
        orders: OrderManager,
        window_mgr: WindowManager,
        risk: RiskEngine,
        result: BacktestResult,
    ) -> None:
        up_wins = tick.outcome == 1 if tick.side == "up" else tick.outcome == 0
        pnl = orders.settle(ticker, up_wins)
        risk.record_realized(pnl)
        window_mgr.settle(ticker)
        result.trades.append(
            TradeRecord(ts=tick.ts, ticker=ticker, side="settle",
                        action="settle", quantity=0, price=0.0, pnl=pnl)
        )
        equity = orders.balance
        result.equity_curve.append((tick.ts, equity))

    def _close(
        self,
        ticker: str,
        side: str,
        pos,
        price: float,
        reason: str,
        orders: OrderManager,
        result: BacktestResult,
    ) -> None:
        proceeds = pos.quantity * price
        pnl = pos.quantity * (price - pos.avg_price)
        orders.balance += proceeds
        orders.realized_pnl += pnl
        pos.add(-pos.quantity, price)
        result.trades.append(
            TradeRecord(ts=0.0, ticker=ticker, side=side, action=reason,
                        quantity=pos.quantity, price=price, pnl=pnl)
        )
