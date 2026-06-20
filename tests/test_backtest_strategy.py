"""Strategy-level backtest tests: fees, no-edge discipline, edge harvesting.

These validate the *machinery* (not a profitability claim about live trading):
given a known edge, the pipeline must profit net of fees; given no edge, it must
not bleed money to fees.
"""

import pytest

from engine.execution.fees import kalshi_fee, breakeven_edge
from engine.backtest.runner import BacktestParams, BacktestRunner
from engine.backtest.synthetic import SynthConfig, generate


def test_kalshi_fee_peaks_at_the_money():
    # Fee is largest near 0.50 and shrinks toward the extremes.
    mid = kalshi_fee(100, 0.50)
    edge_low = kalshi_fee(100, 0.05)
    edge_high = kalshi_fee(100, 0.95)
    assert mid > edge_low and mid > edge_high
    assert kalshi_fee(0, 0.5) == 0.0


def test_breakeven_edge_positive_near_the_money():
    assert breakeven_edge(0.50) > 0.0


def test_efficient_market_does_not_bleed_fees():
    # No mispricing => no edge beyond the spread => strategy should essentially
    # not trade (and certainly not lose a meaningful amount to fees).
    ticks = generate(SynthConfig(mispricing=1.0, n_windows=200))
    res = BacktestRunner(BacktestParams(min_edge=0.04)).run(ticks)
    assert res.total_pnl >= -1.0   # no meaningful bleed
    assert res.n_trades <= 5       # stands down when there is no edge


def test_real_edge_is_profitable_net_of_fees():
    # A genuine, large model-vs-market mispricing must net a profit after fees.
    ticks = generate(SynthConfig(mispricing=1.35, n_windows=300))
    res = BacktestRunner(BacktestParams(min_edge=0.02, min_model_prob=0.50)).run(ticks)
    assert res.n_trades > 50
    assert res.total_pnl > 0.0
    assert res.ev_per_trade is not None and res.ev_per_trade > 0.0
    assert res.total_fees > 0.0    # fees were actually charged


def test_fees_reduce_pnl_versus_gross():
    cfg = SynthConfig(mispricing=1.35, n_windows=200)
    ticks = generate(cfg)
    net = BacktestRunner(BacktestParams(min_edge=0.02, apply_fees=True)).run(ticks)
    gross = BacktestRunner(BacktestParams(min_edge=0.02, apply_fees=False)).run(ticks)
    assert gross.total_pnl > net.total_pnl
    assert net.total_fees > 0.0 and gross.total_fees == 0.0
