"""Synthetic tick generator for validating the strategy machinery.

This does NOT prove the bot will make money live — only real Kalshi data can do
that. What it DOES do is answer controlled questions that are otherwise
impossible without live data:

  * Does the pipeline convert a *known* edge into profit, net of fees?
  * How much model-vs-market mispricing is needed to clear Kalshi's fees
    (the break-even edge)?
  * In an efficient market (no edge), does the strategy correctly avoid
    bleeding money to fees?

Setup: BTC follows a true driftless GBM with vol ``sigma_true``. OUR model is
correctly calibrated (each Tick carries ``sigma_true``). The MARKET prices with
a biased vol (``sigma_true * mispricing``), so when ``mispricing != 1`` the
market is systematically wrong and a real, harvestable edge exists — because the
actual outcomes follow the true process. A half-spread is added to the ask.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from engine.backtest.runner import Tick
from engine.pricing.model import prob_above


@dataclass
class SynthConfig:
    n_windows: int = 400
    window_seconds: float = 900.0      # 15-minute markets
    tick_interval_s: float = 60.0      # one snapshot per minute
    spot0: float = 60000.0
    sigma_true: float = 0.6            # annualized
    mispricing: float = 1.0            # market vol bias (1.0 = efficient market)
    half_spread: float = 0.01          # added to the ask (cost to cross)
    seed: int = 7


def _gbm_step(spot: float, sigma_annual: float, dt_seconds: float, rng: random.Random) -> float:
    dt = dt_seconds / (365.0 * 24.0 * 3600.0)
    z = rng.gauss(0.0, 1.0)
    return spot * math.exp(-0.5 * sigma_annual**2 * dt + sigma_annual * math.sqrt(dt) * z)


def generate(cfg: SynthConfig) -> list[Tick]:
    """Generate a flat list of Ticks (both sides per snapshot) for all windows."""
    rng = random.Random(cfg.seed)
    ticks: list[Tick] = []
    n_steps = int(cfg.window_seconds / cfg.tick_interval_s)

    for w in range(cfg.n_windows):
        # Strike set at-the-money at window open (the hardest, fee-sensitive case).
        spot = cfg.spot0 * math.exp(rng.gauss(0.0, 0.002))
        strike = spot
        # Roll the path forward and remember each snapshot.
        path: list[tuple[float, float]] = []  # (tau, spot)
        for step in range(n_steps):
            tau = cfg.window_seconds - step * cfg.tick_interval_s
            path.append((tau, spot))
            spot = _gbm_step(spot, cfg.sigma_true, cfg.tick_interval_s, rng)
        final_spot = spot
        up_outcome = 1 if final_spot > strike else 0

        ticker = f"SYNTH-{w:04d}"
        for tau, s in path:
            for side in ("up", "down"):
                outcome = up_outcome if side == "up" else (1 - up_outcome)
                # Market's (biased) fair value for this side, then add half-spread.
                mkt_p = prob_above(s, strike, cfg.sigma_true * cfg.mispricing, tau)
                if side == "down":
                    mkt_p = 1.0 - mkt_p
                ask = min(max(mkt_p + cfg.half_spread, 0.01), 0.99)
                ticks.append(Tick(
                    ts=float(w * 100000 + (cfg.window_seconds - tau)),
                    ticker=ticker, side=side, strike=strike, spot=s,
                    sigma=cfg.sigma_true,           # our model is correctly calibrated
                    tau=tau, ask_cents=round(ask * 100), outcome=outcome,
                ))
        # Final settlement tick (tau<=0) so the runner closes the window.
        for side in ("up", "down"):
            outcome = up_outcome if side == "up" else (1 - up_outcome)
            ticks.append(Tick(
                ts=float(w * 100000 + cfg.window_seconds + 1),
                ticker=ticker, side=side, strike=strike, spot=final_spot,
                sigma=cfg.sigma_true, tau=0.0,
                ask_cents=99 if outcome else 1, outcome=outcome,
            ))
    return ticks
