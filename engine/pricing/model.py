"""Fair-value model for Kalshi crypto up/down binary markets.

For a binary that pays $1 if the underlying closes above (``up``) or below
(``down``) a strike ``K`` at expiry, we model the spot price as a driftless
geometric Brownian motion over the (short) time-to-expiry ``tau``:

    P(S_tau > K) = Phi( (ln(S/K) - 0.5 * sigma^2 * tau) / (sigma * sqrt(tau)) )

where ``sigma`` is annualized volatility estimated from recent spot returns and
``Phi`` is the standard normal CDF. Over the very short horizons of 15-minute
and hourly markets, drift is negligible and dominated by volatility, so we omit
a risk-free/drift term. As ``tau -> 0`` the distribution collapses and the
probability snaps to 0/1 around the strike — the near-settlement "pinning"
regime where edge is highest.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from scipy.stats import norm

# Seconds in a (trading-agnostic, 24/7 crypto) year, used to annualize vol.
SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


def prob_above(spot: float, strike: float, sigma_annual: float, tau_seconds: float) -> float:
    """P(S_tau > strike) under driftless GBM. Returns a probability in [0, 1]."""
    if spot <= 0 or strike <= 0:
        return 0.0
    if tau_seconds <= 0 or sigma_annual <= 0:
        # No time / no vol left: deterministic pin around the strike.
        return 1.0 if spot > strike else 0.0
    tau = tau_seconds / SECONDS_PER_YEAR
    vol_sqrt_t = sigma_annual * math.sqrt(tau)
    if vol_sqrt_t <= 1e-12:
        return 1.0 if spot > strike else 0.0
    d = (math.log(spot / strike) - 0.5 * sigma_annual**2 * tau) / vol_sqrt_t
    return float(norm.cdf(d))


def fair_prob(
    side: str, spot: float, strike: float, sigma_annual: float, tau_seconds: float
) -> float:
    """Fair probability that the given ``side`` ("up"/"down") resolves YES."""
    p_above = prob_above(spot, strike, sigma_annual, tau_seconds)
    if side == "up":
        return p_above
    if side == "down":
        return 1.0 - p_above
    raise ValueError(f"unknown side: {side!r}")


@dataclass
class VolEstimator:
    """Rolling realized-volatility estimator from a stream of spot prices.

    Maintains a window of (timestamp, price) samples and annualizes the standard
    deviation of log returns scaled by the average sampling interval.
    """

    lookback_seconds: float = 900.0
    _samples: deque = None  # type: ignore[assignment]

    def __post_init__(self):
        self._samples = deque()

    def add(self, ts: float, price: float) -> None:
        if price <= 0:
            return
        self._samples.append((ts, price))
        cutoff = ts - self.lookback_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def sigma_annual(self) -> float:
        """Annualized vol estimate, or 0.0 if not enough data yet."""
        if len(self._samples) < 3:
            return 0.0
        prices = [p for _, p in self._samples]
        times = [t for t, _ in self._samples]
        log_rets = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        if len(log_rets) < 2:
            return 0.0
        mean = sum(log_rets) / len(log_rets)
        var = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
        std_per_step = math.sqrt(var)
        # Average seconds between samples.
        total_dt = times[-1] - times[0]
        avg_dt = total_dt / (len(times) - 1) if total_dt > 0 else 1.0
        if avg_dt <= 0:
            return 0.0
        # Scale per-step std to per-second, then annualize.
        return std_per_step / math.sqrt(avg_dt) * math.sqrt(SECONDS_PER_YEAR)
