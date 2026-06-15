"""Edge computation and trade-signal generation.

Combines the fair-value model probability with the live Kalshi order book to
decide whether there is a tradeable edge:

    edge = model_prob - ask_price_prob - fee_buffer

If we can buy YES at an ask whose implied probability is meaningfully below our
model's fair probability (after a fee/half-spread haircut), that is a positive
expected-value entry. An order-book imbalance term nudges confidence, and a
``near_close`` flag marks the high-confidence pinning regime in the final
seconds of a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from engine.data.kalshi_ws import OrderBook
from engine.pricing.model import fair_prob


@dataclass
class Signal:
    ticker: str
    side: str               # "up" | "down"  (which contract side resolves YES)
    model_prob: float       # fair P(this side resolves YES)
    ask_prob: float         # cost to buy this side, as a probability (cents/100)
    edge: float             # model_prob - ask_prob - fee_buffer
    imbalance: float        # order-book imbalance in [-1, 1]
    near_close: bool
    tradeable: bool
    reason: str = ""


def book_imbalance(book: OrderBook) -> float:
    """(yes_depth - no_depth) / (yes_depth + no_depth), in [-1, 1]."""
    yes_depth = sum(book.yes.values())
    no_depth = sum(book.no.values())
    total = yes_depth + no_depth
    if total <= 0:
        return 0.0
    return (yes_depth - no_depth) / total


def evaluate(
    *,
    ticker: str,
    side: str,
    spot: float,
    strike: float,
    sigma_annual: float,
    tau_seconds: float,
    book: OrderBook,
    min_edge: float,
    fee_buffer: float,
    near_close_seconds: float = 20.0,
) -> Optional[Signal]:
    """Evaluate a single market side and return a Signal (or None if no book).

    ``side`` is the directional bet: "up" buys YES (resolves YES if spot ends
    above strike); "down" buys NO. We compare our fair probability for that
    direction against the cost to buy it.
    """
    ask = book.ask_for(side)
    if ask is None:
        return None

    model_p = fair_prob(side, spot, strike, sigma_annual, tau_seconds)
    ask_prob = ask / 100.0
    edge = model_p - ask_prob - fee_buffer
    imbalance = book_imbalance(book)
    near_close = tau_seconds <= near_close_seconds

    tradeable = edge >= min_edge
    reason = "edge >= min_edge" if tradeable else "edge below threshold"
    if near_close:
        # Near settlement, require the spot to be clearly on the right side of
        # the strike to avoid coin-flip pins.
        clearly = (model_p > 0.9) if side == "up" else (model_p > 0.9)
        if tradeable and not clearly:
            tradeable = False
            reason = "near close but model not confident"

    return Signal(
        ticker=ticker,
        side=side,
        model_prob=model_p,
        ask_prob=ask_prob,
        edge=edge,
        imbalance=imbalance,
        near_close=near_close,
        tradeable=tradeable,
        reason=reason,
    )
