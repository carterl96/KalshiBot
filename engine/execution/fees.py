"""Kalshi trading-fee model.

Kalshi charges a per-trade fee that is largest for coin-flip (0.50) contracts
and shrinks toward the extremes. The published formula is:

    fee = roundup( rate * C * P * (1 - P) )   in dollars, rounded up to the cent

where ``C`` is the contract count, ``P`` is the price in dollars [0, 1], and
``rate`` is the venue fee rate (0.07 for most markets; some are 0.035).

Fees are the single biggest drag on a high-frequency binary strategy: at P=0.50
the fee is ~1.75c per contract per side at 0.07, so a round trip near the money
costs ~3.5c — which must be cleared by edge before a trade is +EV. Modeling them
explicitly is essential to any honest backtest or EV calculation.
"""

from __future__ import annotations

import math

DEFAULT_FEE_RATE = 0.07


def kalshi_fee(contracts: int, price_prob: float, rate: float = DEFAULT_FEE_RATE) -> float:
    """Return the trading fee in USD for ``contracts`` at ``price_prob`` (in [0,1])."""
    if contracts <= 0:
        return 0.0
    p = min(max(price_prob, 0.0), 1.0)
    cents = math.ceil(rate * contracts * p * (1.0 - p) * 100.0)
    return cents / 100.0


def breakeven_edge(price_prob: float, rate: float = DEFAULT_FEE_RATE) -> float:
    """Minimum model-vs-price edge (in probability units) needed for one
    contract to be +EV after a single entry fee at ``price_prob``.

    Entry fee per contract = kalshi_fee(1, p). Each contract's gross expected
    profit from an edge ``e`` is ``e`` dollars (model_prob - price), so the
    edge must exceed the per-contract fee to break even.
    """
    return kalshi_fee(1, price_prob, rate)
